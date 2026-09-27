"""Seed the local devstack with the data DonnyT needs to be tested against.

The world is a small team building a todo API in Go (``test/devstack/todo``):
three closed sprints that built v0, a backlog of features and bugs, real code
in GitLab with one commit per ticket, and the team's person notes in the vault.
``team.py`` then plays the team through new sprints; see SIMULATION.md.

Safe to re-run: every run resets to the same known state (the Jira project is
deleted and rebuilt, GitLab ``main`` is replaced and open work removed, the
vault's notes are rewritten, the Confluence pages updated). Reads tokens from
test/devstack/donnyt/.env and, when done, points test/devstack/donnyt/config.toml
at what it created.

    python test/devstack/seed.py                 # everything
    python test/devstack/seed.py jira vault      # just these

Stdlib only, like the toolkit itself.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENV = HERE / "donnyt" / ".env"
TOKENS = HERE / "donnyt" / "team-tokens.json"
PATCHES = HERE / "todo" / "patches"

GITLAB_WEB = "http://127.0.0.1:8929"
GITLAB = f"{GITLAB_WEB}/api/v4"
PROJECT = "team/todo"

# (login, display name, role, focus). The login is the Jira username
# and the GitLab username; the display name must match Jira's exactly.
PEOPLE = [
    ("maya", "Maya Cohen", "Backend lead",
     ["Own the storage layer and anything that changes the data model",
      "Review every change to internal/todo/store.go"]),
    ("dan", "Dan Levi", "Platform",
     ["Runtime, configuration, deployment, anything in cmd/",
      "Keep the build and the tests fast"]),
    ("noa", "Noa Katz", "API features",
     ["New endpoints and query parameters",
      "Pair with Tamar on API docs"]),
    ("omer", "Omer Shapiro", "Reliability and security",
     ["Validation, error handling, rate limiting, auth",
      "Mentor Lior; review his MRs"]),
    ("lior", "Lior Ben-David", "Junior engineer",
     ["Grow through middleware and tests, one layer at a time",
      "Take one ticket a sprint outside his comfort zone, paired with Omer"]),
    ("tamar", "Tamar Adler", "Engineer, part-time (50%)",
     ["Docs and tests",
      "Nothing on the critical path of a sprint goal"]),
]
NAMES = {login: display for login, display, *_ in PEOPLE}


def env(name: str) -> str:
    for line in ENV.read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition("=")
        if key.strip() == name:
            return value.strip()
    return ""


def call(method: str, url: str, token_header: dict[str, str], body: object = None) -> tuple[int, object]:
    data = json.dumps(body).encode() if body is not None else None
    headers = {**token_header, "Content-Type": "application/json", "X-Atlassian-Token": "no-check"}
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.status, _json(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, _json(exc.read())


def _json(raw: bytes) -> object:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"_raw": raw.decode("utf-8", "replace")[:500]}


def ok(result: tuple[int, object], what: str) -> object:
    status, body = result
    if status >= 300:
        raise SystemExit(f"{what} failed: HTTP {status} {body}")
    return body


def git(*args: str, cwd: Path, env_: dict[str, str] | None = None) -> str:
    """Run git without any credential helper, so a token URL never prompts."""
    result = subprocess.run(
        ["git", "-c", "credential.helper=", "-c", "core.autocrlf=false", *args],
        cwd=cwd, env={**os.environ, **(env_ or {})}, capture_output=True, text=True,
    )
    if result.returncode:
        raise SystemExit(f"git {' '.join(args[:2])} failed:\n{result.stderr.strip()}")
    return result.stdout


# ---------------------------------------------------------------- gitlab


def gitlab_admin() -> tuple[dict[str, str], str]:
    token = env("GITLAB_TOKEN")
    if not token:
        raise SystemExit(f"GITLAB_TOKEN is empty in {ENV}")
    return {"PRIVATE-TOKEN": token}, token


def project_url() -> str:
    return f"{GITLAB}/projects/{urllib.parse.quote(PROJECT, safe='')}"


def seed_gitlab() -> None:
    auth, root_token = gitlab_admin()
    api = lambda method, path, body=None: call(method, GITLAB + path, auth, body)  # noqa: E731

    # The team, as real users: commits, MRs and reviews carry their names.
    users: dict[str, int] = {}
    for login, display, *_ in PEOPLE:
        found = ok(api("GET", f"/users?username={login}"), f"find user {login}")
        if not found:
            found = [ok(api("POST", "/users", {
                "username": login, "name": display, "email": f"{login}@devstack.local",
                "password": secrets.token_urlsafe(18), "skip_confirmation": True,  # nobody logs in as them
            }), f"create user {login}")]
        users[login] = found[0]["id"]
    print(f"  users: {', '.join(users)}")

    project = project_url()
    if call("GET", project, auth)[0] != 200:
        group, name = PROJECT.split("/")
        status, found = api("GET", f"/groups/{group}")
        if status != 200:
            found = ok(api("POST", "/groups", {"name": group, "path": group, "visibility": "private"}),
                       "create group")
        ok(api("POST", "/projects", {"name": name, "path": name, "namespace_id": found["id"]}),
           "create project")
        print(f"  created project {PROJECT}")
    for login, uid in users.items():
        call("POST", f"{project}/members", auth, {"user_id": uid, "access_level": 30})  # 409 if already in

    # Start clean: no open or old MRs, no branches but main.
    mrs = ok(call("GET", f"{project}/merge_requests?state=all&per_page=100", auth), "list MRs")
    for mr in mrs:
        call("DELETE", f"{project}/merge_requests/{mr['iid']}", auth)
    branches = ok(call("GET", f"{project}/repository/branches?per_page=100", auth), "list branches")
    for branch in branches if isinstance(branches, list) else []:
        if branch["name"] != "main":
            call("DELETE", f"{project}/repository/branches/{urllib.parse.quote(branch['name'], safe='')}", auth)

    # Replay v0: one commit per ticket, committed as its author on its date.
    patches = sorted(PATCHES.glob("*.patch"))
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        git("init", "-q", "-b", "main", cwd=repo)
        for patch in patches:
            header = patch.read_text(encoding="utf-8").split("\n\n", 1)[0]
            name, email = re.search(r"^From: (.+?) <(.+?)>$", header, re.M).groups()
            git("am", "-q", "--committer-date-is-author-date", str(patch), cwd=repo, env_={
                "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": email,
            })
        # main is protected; lift it for the force-push, then protect it the
        # way a team would: merge through MRs, no direct pushes by developers.
        call("DELETE", f"{project}/protected_branches/main", auth)
        remote = f"http://root:{root_token}@{GITLAB_WEB.removeprefix('http://')}/{PROJECT}.git"
        git("push", "-q", "--force", remote, "main", cwd=repo)
        ok(call("POST", f"{project}/protected_branches", auth, {
            "name": "main", "push_access_level": 40, "merge_access_level": 30,
        }), "protect main")
    call("PUT", project, auth, {"default_branch": "main"})
    print(f"  {PROJECT} main: {len(patches)} commits, one per v0 ticket")

    # A token per person, for team.py to act as them. Old ones are revoked.
    tokens: dict[str, str] = {}
    expires = (date.today() + timedelta(days=300)).isoformat()
    for login, uid in users.items():
        existing = ok(api("GET", f"/users/{uid}/impersonation_tokens?state=active"), f"tokens {login}")
        for token in existing:
            if token["name"] == "donnyt-sim":
                api("DELETE", f"/users/{uid}/impersonation_tokens/{token['id']}")
        created = ok(api("POST", f"/users/{uid}/impersonation_tokens", {
            "name": "donnyt-sim", "scopes": ["api", "write_repository"], "expires_at": expires,
        }), f"token for {login}")
        tokens[login] = created["token"]
    TOKENS.write_text(json.dumps(tokens, indent=2) + "\n", encoding="utf-8")
    print(f"  tokens: {TOKENS.relative_to(HERE.parent.parent)}")


# ------------------------------------------------------------------ jira

JIRA = "http://127.0.0.1:8080"
KEY = "TEAM"

# Two-week sprints, Sunday to Thursday. All three built v0 and are closed;
# the next sprint is planned from a brief, through DonnyT.
SPRINTS = [
    ("TEAM Sprint 1", "2026-08-16", "2026-08-27", "Stand up the todo API: create and list"),
    ("TEAM Sprint 2", "2026-08-30", "2026-09-10", "Full CRUD with clean errors"),
    ("TEAM Sprint 3", "2026-09-13", "2026-09-24", "v0: todos can be completed, the API is documented and shuts down cleanly"),
]

# (summary, type, assignee, sprints it sat in, sprint finished in -- or its
# status now, description). Created in order: the first ten are TEAM-1..10 and
# match the commits in todo/patches. Nothing is estimated -- the team does not
# use story points. TEAM-4 spills over from Sprint 2 into Sprint 3.
#
# The backlog is deliberately uneven, from a one-line fix to a cross-cutting
# change, so estimation has something to tell apart. TEAM-11 and TEAM-12 are
# real bugs in v0.
ISSUES: list[tuple[str, str, str, list[int], int | str, str]] = [
    ("Project skeleton and health check", "Task", "dan", [1], 1,
     "Go module, cmd/todo, GET /healthz returning ok."),
    ("Todo model and in-memory store", "Story", "maya", [1], 1,
     "Todo type and a concurrency-safe in-memory store with create, list and get."),
    ("Create and list todos", "Story", "noa", [1], 1,
     "POST /todos and GET /todos."),
    ("Get, update and delete a todo", "Story", "noa", [2, 3], 3,
     "GET, PATCH and DELETE /todos/{id}. 404 for an unknown id, 400 for a bad one."),
    ("Validate input and return JSON errors", "Story", "omer", [2], 2,
     "Titles required, trimmed, at most 200 characters. Every error is {\"error\": \"...\"}."),
    ("Request logging middleware", "Story", "lior", [2], 2,
     "One log line per request: method, path, status, duration."),
    ("Handler tests", "Task", "tamar", [2], 2,
     "httptest coverage for create and list, including bad input."),
    ("Graceful shutdown and config from env", "Task", "dan", [3], 3,
     "TODO_ADDR for the listen address; drain in-flight requests on SIGTERM."),
    ("Mark a todo done or undone", "Story", "maya", [3], 3,
     "PATCH /todos/{id} accepts \"done\"; leaving it out keeps the current state."),
    ("README with API examples", "Task", "tamar", [3], 3,
     "How to run it, every endpoint, curl examples."),
    # -- backlog --
    ("List returns todos in random order", "Bug", "", [], "To Do",
     "GET /todos returns the same todos in a different order on each call. "
     "They should come back oldest first (by id)."),
    ("PATCH without a title blanks the title", "Bug", "", [], "To Do",
     "PATCH /todos/1 with {\"done\": true} sets the title to \"\". A PATCH should change only the "
     "fields it sends, and a title that is sent should be validated like on create."),
    ("Filter todos by done state", "Story", "", [], "To Do",
     "GET /todos?done=true|false. Any other value is a 400."),
    ("Search todos by title", "Story", "", [], "To Do",
     "GET /todos?q=milk: case-insensitive substring match. Combines with ?done."),
    ("Complete several todos at once", "Story", "", [], "To Do",
     "POST /todos/complete with {\"ids\": [1, 2]}. All or nothing: an unknown id fails the request."),
    ("Due dates on todos", "Story", "", [], "To Do",
     "Optional due date (YYYY-MM-DD) on create and update, validated. GET /todos?overdue=true."),
    ("Priority and sorting", "Story", "", [], "To Do",
     "Priority low / normal / high (default normal). GET /todos?sort=priority|created|due."),
    ("Tags on todos", "Story", "", [], "To Do",
     "Up to 10 tags per todo, lower-cased. GET /todos?tag=home."),
    ("Paginate the todo list", "Story", "", [], "To Do",
     "?limit (default 50, max 200) and ?offset; total count in an X-Total-Count header."),
    ("Soft delete and restore", "Story", "", [], "To Do",
     "DELETE hides a todo; POST /todos/{id}/restore brings it back; GET /todos?deleted=true lists them."),
    ("Keep todos across restarts", "Story", "", [], "To Do",
     "Persist to a JSON file (TODO_DATA). Writes are atomic: a crash never leaves a half-written file."),
    ("Rate limit the API", "Story", "", [], "To Do",
     "Per client IP, token bucket, configurable. 429 with Retry-After when exceeded. /healthz is exempt."),
    ("API keys", "Story", "", [], "To Do",
     "Every request except /healthz needs X-API-Key, one of TODO_API_KEYS. 401 otherwise."),
    ("OpenAPI description of the API", "Task", "", [], "To Do",
     "openapi.json served at /openapi.json, with a test that every registered route is described."),
    ("Storage behind an interface", "Story", "", [], "To Do",
     "Handlers depend on a Store interface, not the in-memory type, so a file or database store "
     "can be swapped in. No behaviour change."),
    ("Users with their own todo lists", "Story", "", [], "To Do",
     "Each API key belongs to a user; todos are scoped to their owner. Another user's todo is a 404."),
]


def seed_jira() -> dict[str, object]:
    token = env("JIRA_PAT")
    if not token:
        raise SystemExit(f"JIRA_PAT is empty in {ENV}")
    auth = {"Authorization": f"Bearer {token}"}
    api = lambda method, path, body=None: call(method, JIRA + path, auth, body)  # noqa: E731

    # People -- only the display name matters to DonnyT; nobody logs in as them.
    for name, display, *_ in PEOPLE:
        if api("GET", f"/rest/api/2/user?username={name}")[0] != 200:
            ok(api("POST", "/rest/api/2/user", {
                "name": name, "displayName": display, "emailAddress": f"{name}@devstack.local",
                "password": "Unused-" + token[:12], "applicationKeys": ["jira-software"],
            }), f"create user {name}")
    print(f"  users: {', '.join(d for _, d, *_ in PEOPLE)}")

    # Start from a clean project so a re-run gives the same history.
    if api("GET", f"/rest/api/2/project/{KEY}")[0] == 200:
        for board in (api("GET", f"/rest/agile/1.0/board?projectKeyOrId={KEY}")[1] or {}).get("values", []):
            api("DELETE", f"/rest/agile/1.0/board/{board['id']}")
        ok(api("DELETE", f"/rest/api/2/project/{KEY}"), "delete old project")
        print(f"  removed the previous {KEY} project")
    # Default new issues to unassigned, not the project lead -- otherwise every
    # backlog item looks like the admin's work. (Jira 10 allows unassigned
    # issues out of the box; its REST API does not expose that switch.)
    ok(api("POST", "/rest/api/2/project", {
        "key": KEY, "name": "Team Todo", "lead": "admin",
        "projectTypeKey": "software", "assigneeType": "UNASSIGNED",
        "projectTemplateKey": "com.pyxis.greenhopper.jira:gh-scrum-template",
    }), "create project")

    roles = ok(api("GET", f"/rest/api/2/project/{KEY}/role"), "list roles")
    for role, url in roles.items():
        if role != "Administrators":
            path = urllib.parse.urlparse(url).path
            api("POST", path, {"user": [n for n, *_ in PEOPLE]})

    boards = ok(api("GET", f"/rest/agile/1.0/board?projectKeyOrId={KEY}"), "find board")["values"]
    if not boards:
        filt = ok(api("POST", "/rest/api/2/filter", {
            "name": f"{KEY} board", "jql": f"project = {KEY} ORDER BY Rank ASC"}), "create filter")
        boards = [ok(api("POST", "/rest/agile/1.0/board", {
            "name": f"{KEY} board", "type": "scrum", "filterId": filt["id"]}), "create board")]
    board = boards[0]["id"]

    fields = ok(api("GET", "/rest/api/2/field"), "list fields")
    points = next((f["id"] for f in fields if f["name"] == "Story Points"), "")
    print(f"  project {KEY}, board {board}, story points field {points or '(none)'}")

    keys: list[str] = []
    for summary, kind, who, _, _, description in ISSUES:
        fields_ = {"project": {"key": KEY}, "summary": summary, "issuetype": {"name": kind},
                   "description": description}
        if who:
            fields_["assignee"] = {"name": who}
        keys.append(ok(api("POST", "/rest/api/2/issue", {"fields": fields_}), f"create {summary!r}")["key"])
    print(f"  issues: {keys[0]} .. {keys[-1]} ({len(keys)}), none estimated")

    def move(key: str, status: str) -> None:
        options = ok(api("GET", f"/rest/api/2/issue/{key}/transitions"), f"transitions {key}")
        match = next((t for t in options["transitions"] if t["to"]["name"] == status), None)
        if match:
            ok(api("POST", f"/rest/api/2/issue/{key}/transitions", {"transition": {"id": match["id"]}}),
               f"move {key} to {status}")

    # Replay the history sprint by sprint: fill it, start it, finish what was
    # finished in it, leave the rest in progress, close it.
    for n, (name, start, end, goal) in enumerate(SPRINTS, 1):
        dates = {"startDate": f"{start}T09:00:00.000+03:00", "endDate": f"{end}T18:00:00.000+03:00"}
        sprint = ok(api("POST", "/rest/agile/1.0/sprint", {
            "name": name, "originBoardId": board, "goal": goal, **dates}), f"create {name}")
        members = [i for i, issue in enumerate(ISSUES) if n in issue[3]]
        ok(api("POST", f"/rest/agile/1.0/sprint/{sprint['id']}/issue",
               {"issues": [keys[i] for i in members]}), f"fill {name}")
        ok(api("POST", f"/rest/agile/1.0/sprint/{sprint['id']}", {"state": "active", **dates}), f"start {name}")
        for i in members:
            if ISSUES[i][4] == n:
                move(keys[i], "In Progress")
                move(keys[i], "Done")
            else:
                move(keys[i], "In Progress")
        ok(api("POST", f"/rest/agile/1.0/sprint/{sprint['id']}", {"state": "closed"}), f"close {name}")
        done = sum(1 for i in members if ISSUES[i][4] == n)
        print(f"  {name}: closed, {done}/{len(members)} done")

    return {"board": board, "points": points}


# ------------------------------------------------------------------ vault

VAULT = HERE / "donnyt" / "vault"
REPO_VAULT = HERE.parent.parent / "vault"


def seed_vault() -> None:
    """Reset the devstack vault to the team: person notes with Focus, the repo's templates."""
    for folder in ("People", "Sprints", "MRs", "Projects", "Decisions", "Meetings", "Topics"):
        for note in (VAULT / folder).glob("*.md"):
            if note.name != "README.md":
                note.unlink()
    shutil.copytree(REPO_VAULT / "_templates", VAULT / "_templates", dirs_exist_ok=True)
    for readme in REPO_VAULT.glob("*/README.md"):
        if readme.parent.name != "_templates":
            (VAULT / readme.parent.name).mkdir(parents=True, exist_ok=True)
            shutil.copy(readme, VAULT / readme.parent.name / "README.md")

    for login, display, role, focus in PEOPLE:
        note = VAULT / "People" / f"{display}.md"
        note.write_text("\n".join([
            "---", "type: person", f"role: {role}", f"jira: {login}", f"gitlab: {login}",
            "tags:", "  - person", "---", "",
            f"# {display}", "",
            "## Focus", "", *[f"- {line}" for line in focus], "",
            "## Context", "", f"{role} on the todo API team.", "",
            "## One-on-ones", "",
        ]) + "\n", encoding="utf-8")
    print(f"  {len(PEOPLE)} person notes, templates, empty Sprints/ at {VAULT.relative_to(HERE.parent.parent)}")


# ------------------------------------------------------------ confluence

CONFLUENCE = "http://127.0.0.1:8090"
SPACE = "ENG"
PRD_TITLE = "PRD Template"

# A product requirements template that comes *before* the tickets: it starts
# from the problem and the proposed solution, spends most of its length on the
# user experience, and ends with requirements product can cut tickets from.
# Macro shapes for the converter: callouts, placeholders, status labels in
# tables, a task list and an expand.
PRD = """\
<ac:structured-macro ac:name="info"><ac:rich-text-body><p>Write this before any tickets exist. Start from the problem, describe what the solution looks like to the user, and end with requirements that product and engineering can turn into tickets. Keep every heading; if a section does not apply, write N/A and say why.</p></ac:rich-text-body></ac:structured-macro>
<table><tbody>
<tr><th>Status</th><td><ac:structured-macro ac:name="status"><ac:parameter ac:name="colour">Grey</ac:parameter><ac:parameter ac:name="title">Draft</ac:parameter></ac:structured-macro></td></tr>
<tr><th>Owner</th><td><ac:placeholder>Product owner and team lead.</ac:placeholder></td></tr>
<tr><th>Target release</th><td><ac:placeholder>Quarter, milestone or date.</ac:placeholder></td></tr>
<tr><th>Tickets</th><td><ac:placeholder>Filled in once the PRD is approved and tickets are created.</ac:placeholder></td></tr>
</tbody></table>
<h2>Problem</h2>
<p><ac:placeholder>Who has the problem, what it costs them today, and how we know. Evidence over opinion.</ac:placeholder></p>
<h2>Goals</h2>
<table><tbody>
<tr><th>Goal</th><th>Metric</th><th>Target</th></tr>
<tr><td><ac:placeholder>The outcome we want.</ac:placeholder></td><td><ac:placeholder>How we measure it.</ac:placeholder></td><td><ac:placeholder>The number that means success.</ac:placeholder></td></tr>
</tbody></table>
<h2>Non-goals</h2>
<ul><li><ac:placeholder>What this deliberately does not do, so nobody assumes it will.</ac:placeholder></li></ul>
<h2>Users</h2>
<ul><li><ac:placeholder>Each kind of user, what they are trying to get done, and how often.</ac:placeholder></li></ul>
<h2>Proposed solution</h2>
<p><ac:placeholder>What we will build, in a paragraph a new team member could follow. The shape of the solution, not the implementation.</ac:placeholder></p>
<h2>User experience</h2>
<h3>User flows</h3>
<ol><li><ac:placeholder>Step by step, from where the user starts to the outcome they wanted. One list per flow.</ac:placeholder></li></ol>
<h3>Screens</h3>
<table><tbody>
<tr><th>Screen</th><th>Purpose</th><th>Shows</th><th>User can</th></tr>
<tr><td><ac:placeholder>Name.</ac:placeholder></td><td><ac:placeholder>Why the user is here.</ac:placeholder></td><td><ac:placeholder>The information on it.</ac:placeholder></td><td><ac:placeholder>The actions available.</ac:placeholder></td></tr>
</tbody></table>
<h3>States and edge cases</h3>
<ul><li><ac:placeholder>Empty, loading, error, no permission, very large data, first-time use. What the user sees in each.</ac:placeholder></li></ul>
<h3>Mockups</h3>
<p><ac:placeholder>Mockups or wireframes for each screen above, or a link to the design file.</ac:placeholder></p>
<h2>Requirements</h2>
<table><tbody>
<tr><th>ID</th><th>Requirement</th><th>Priority</th><th>Acceptance criteria</th></tr>
<tr><td>R1</td><td><ac:placeholder>What the product must do, from the user's side. Each one should be small enough to become a ticket.</ac:placeholder></td><td><ac:structured-macro ac:name="status"><ac:parameter ac:name="colour">Red</ac:parameter><ac:parameter ac:name="title">Must</ac:parameter></ac:structured-macro></td><td><ac:placeholder>Testable: given / when / then.</ac:placeholder></td></tr>
<tr><td>R2</td><td><ac:placeholder>What the product should do.</ac:placeholder></td><td><ac:structured-macro ac:name="status"><ac:parameter ac:name="colour">Yellow</ac:parameter><ac:parameter ac:name="title">Should</ac:parameter></ac:structured-macro></td><td><ac:placeholder>Testable: given / when / then.</ac:placeholder></td></tr>
</tbody></table>
<h2>Non-functional requirements</h2>
<ul><li><ac:placeholder>Performance, availability, security, privacy, accessibility. Numbers, not adjectives.</ac:placeholder></li></ul>
<h2>Dependencies and risks</h2>
<table><tbody>
<tr><th>Item</th><th>Type</th><th>Mitigation</th></tr>
<tr><td><ac:placeholder>Another team, a service, a vendor, a data migration.</ac:placeholder></td><td><ac:placeholder>Dependency or risk.</ac:placeholder></td><td><ac:placeholder>What we do about it.</ac:placeholder></td></tr>
</tbody></table>
<h2>Open questions</h2>
<ul><li><ac:placeholder>Anything undecided, with who owns the answer.</ac:placeholder></li></ul>
<h2>Sign-off</h2>
<ac:task-list>
<ac:task><ac:task-id>1</ac:task-id><ac:task-status>incomplete</ac:task-status><ac:task-body>Product</ac:task-body></ac:task>
<ac:task><ac:task-id>2</ac:task-id><ac:task-status>incomplete</ac:task-status><ac:task-body>Engineering</ac:task-body></ac:task>
<ac:task><ac:task-id>3</ac:task-id><ac:task-status>incomplete</ac:task-status><ac:task-body>Design</ac:task-body></ac:task>
<ac:task><ac:task-id>4</ac:task-id><ac:task-status>incomplete</ac:task-status><ac:task-body>QA</ac:task-body></ac:task>
</ac:task-list>
<ac:structured-macro ac:name="expand"><ac:parameter ac:name="title">Appendix</ac:parameter><ac:rich-text-body><p>Research notes, customer quotes, links to prior decisions.</p></ac:rich-text-body></ac:structured-macro>
<ac:structured-macro ac:name="warning"><ac:rich-text-body><p>Anything that touches personal data, payments or authentication needs a security review before sign-off.</p></ac:rich-text-body></ac:structured-macro>
"""


def seed_confluence() -> dict[str, object]:
    token = env("CONFLUENCE_PAT")
    if not token:
        raise SystemExit(f"CONFLUENCE_PAT is empty in {ENV}")
    auth = {"Authorization": f"Bearer {token}"}
    api = lambda method, path, body=None: call(method, CONFLUENCE + path, auth, body)  # noqa: E731

    if api("GET", f"/rest/api/space/{SPACE}")[0] != 200:
        ok(api("POST", "/rest/api/space", {
            "key": SPACE, "name": "Engineering",
            "description": {"plain": {"value": "Team engineering docs.", "representation": "plain"}},
        }), "create space")
        print(f"  created space {SPACE}")

    def upsert(title: str, storage: str) -> str:
        found = ok(api("GET", f"/rest/api/content?spaceKey={SPACE}&title={urllib.parse.quote(title)}&expand=version"),
                   f"find {title!r}")["results"]
        body = {"type": "page", "title": title, "space": {"key": SPACE},
                "body": {"storage": {"value": storage, "representation": "storage"}}}
        if found:
            body["version"] = {"number": found[0]["version"]["number"] + 1}
            page = ok(api("PUT", f"/rest/api/content/{found[0]['id']}", body), f"update {title!r}")
        else:
            page = ok(api("POST", "/rest/api/content", body), f"create {title!r}")
        return str(page["id"])

    plans_id = upsert("Sprint Plans", "<p>Sprint plans published by DonnyT live under this page.</p>")
    prd_id = upsert(PRD_TITLE, PRD)
    prds_id = upsert("Product Requirements", "<p>PRDs published by DonnyT live under this page.</p>")
    print(f"  space {SPACE}: sprint plans page {plans_id}, "
          f"PRD template {prd_id}, PRDs page {prds_id}")
    return {"plans": plans_id, "prd_template": prd_id, "prds": prds_id}


# ------------------------------------------------------------ donnyt config

CONFIG = HERE / "donnyt" / "config.toml"


def write_config(jira: dict[str, object] | None, confluence: dict[str, object] | None) -> None:
    """Point the devstack's DonnyT config at what was just created."""
    text = CONFIG.read_text(encoding="utf-8")

    def setting(key: str, value: str) -> None:
        nonlocal text
        text = re.sub(rf"(?m)^{key}\s*=.*$", lambda _: f"{key} = {value}", text, count=1)

    setting("default_project", f'"{PROJECT}"')
    # The team, and its week: Sunday to Thursday.
    text = re.sub(r"(?ms)^\[team\]\n.*?(?=^\[)", "", text)
    text = re.sub(r"(?ms)^\[\[team\.members\]\].*", "", text).rstrip() + "\n\n"
    text += '[team]\nweekend = ["Fri", "Sat"]\n\n' + "\n".join(
        f'[[team.members]]\nname = "{display}"\njira = "{login}"\ngitlab = "{login}"\n'
        for login, display, *_ in PEOPLE
    )
    if jira:
        setting("board_id", str(jira["board"]))
        if jira["points"]:
            setting("story_points_field", f'"{jira["points"]}"')
    if confluence:
        for key, value in (
            ("sprint_plan_parent_page_id", confluence["plans"]),
            ("prd_template_page_id", confluence["prd_template"]),
            ("prd_parent_page_id", confluence["prds"]),
        ):
            if re.search(rf"(?m)^{key}\s*=", text):
                setting(key, f'"{value}"')
            else:
                text = text.replace("[confluence]\n", f'[confluence]\n{key} = "{value}"\n', 1)
    CONFIG.write_text(text, encoding="utf-8")
    print(f"donnyt: updated {CONFIG.relative_to(HERE.parent.parent)}")


SEEDERS = {"gitlab": seed_gitlab, "jira": seed_jira, "confluence": seed_confluence, "vault": seed_vault}


def main() -> int:
    targets = sys.argv[1:] or list(SEEDERS)
    results: dict[str, object] = {}
    for target in targets:
        if target not in SEEDERS:
            raise SystemExit(f"Unknown target {target!r}; choose from {', '.join(SEEDERS)}")
        print(f"{target}:")
        results[target] = SEEDERS[target]()
    write_config(results.get("jira"), results.get("confluence"))  # type: ignore[arg-type]
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
