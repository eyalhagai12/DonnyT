"""Seed the local devstack with the data DonnyT needs to be tested against.

Safe to re-run: every run resets to the same known state (the Jira project is
deleted and rebuilt, the GitLab branch reset, the Confluence pages updated).
Reads tokens from test/devstack/donnyt/.env and, when done, points
test/devstack/donnyt/config.toml at what it created.

    python test/devstack/seed.py                 # everything
    python test/devstack/seed.py jira confluence # just these

Stdlib only, like the toolkit itself.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENV = HERE / "donnyt" / ".env"

GITLAB = "http://127.0.0.1:8929/api/v4"
PROJECT = "team/api"
BRANCH = "feature/TEAM-1-order-cache"

# The demo change: a service split plus a read cache, in three commits, so an
# MR description has something real to describe.
COMMITS = [
    (
        "TEAM-1 Split OrderService into reader and writer",
        {
            "src/orders/reader.py": '''\
class OrderReader:
    """Read side of orders. Safe to cache: it never writes."""

    def __init__(self, db):
        self.db = db

    def get(self, order_id):
        return self.db.fetch_one("SELECT * FROM orders WHERE id = %s", order_id)
''',
            "src/orders/writer.py": '''\
class OrderWriter:
    """Write side of orders."""

    def __init__(self, db):
        self.db = db

    def save(self, order):
        self.db.execute(
            "INSERT INTO orders (id, total) VALUES (%s, %s)", order.id, order.total
        )
''',
        },
    ),
    (
        "TEAM-1 Cache order reads for 60 seconds",
        {
            "src/orders/cache.py": '''\
import time


class CachedOrderReader:
    """Wraps an OrderReader with a per-order time-to-live cache."""

    def __init__(self, reader, ttl=60):
        self.reader = reader
        self.ttl = ttl
        self._cache = {}

    def get(self, order_id):
        hit = self._cache.get(order_id)
        if hit and time.monotonic() - hit[0] < self.ttl:
            return hit[1]
        value = self.reader.get(order_id)
        self._cache[order_id] = (time.monotonic(), value)
        return value
''',
        },
    ),
    (
        "TEAM-1 Test cache hits and expiry",
        {
            "tests/test_cache.py": '''\
from src.orders.cache import CachedOrderReader


class FakeReader:
    def __init__(self):
        self.calls = 0

    def get(self, order_id):
        self.calls += 1
        return {"id": order_id}


def test_second_read_is_cached():
    reader = FakeReader()
    cached = CachedOrderReader(reader)
    cached.get(1)
    cached.get(1)
    assert reader.calls == 1


def test_expired_entry_is_refetched():
    reader = FakeReader()
    cached = CachedOrderReader(reader, ttl=0)
    cached.get(1)
    cached.get(1)
    assert reader.calls == 2
''',
        },
    ),
]


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


# ---------------------------------------------------------------- gitlab


def seed_gitlab() -> None:
    token = env("GITLAB_TOKEN")
    if not token:
        raise SystemExit(f"GITLAB_TOKEN is empty in {ENV}")
    auth = {"PRIVATE-TOKEN": token}
    project = f"{GITLAB}/projects/{urllib.parse.quote(PROJECT, safe='')}"

    status, _ = call("GET", project, auth)
    if status != 200:
        group, name = PROJECT.split("/")
        status, found = call("GET", f"{GITLAB}/groups/{group}", auth)
        if status != 200:
            found = ok(call("POST", f"{GITLAB}/groups", auth,
                            {"name": group, "path": group, "visibility": "private"}), "create group")
        ok(call("POST", f"{GITLAB}/projects", auth,
                {"name": name, "path": name, "namespace_id": found["id"],
                 "initialize_with_readme": True, "default_branch": "main"}), "create project")
        print(f"  created project {PROJECT}")

    # Reset the branch so every run produces the same three commits.
    call("DELETE", f"{project}/repository/branches/{urllib.parse.quote(BRANCH, safe='')}", auth)
    for n, (message, files) in enumerate(COMMITS):
        body: dict = {
            "branch": BRANCH,
            "commit_message": message,
            "actions": [
                {"action": "create", "file_path": path, "content": content}
                for path, content in files.items()
            ],
        }
        if n == 0:
            body["start_branch"] = "main"
        status, result = call("POST", f"{project}/repository/commits", auth, body)
        if status not in (200, 201):
            raise SystemExit(f"Commit {message!r} failed: HTTP {status} {result}")
        print(f"  committed {result['short_id']}  {message}")

    _, compare = call("GET", f"{project}/repository/compare?from=main&to={urllib.parse.quote(BRANCH)}", auth)
    print(f"gitlab: {PROJECT} {BRANCH} -- {len(compare['commits'])} commits, {len(compare['diffs'])} files")


# ------------------------------------------------------------------ jira

JIRA = "http://127.0.0.1:8080"
KEY = "TEAM"

PEOPLE = [("maya", "Maya Cohen", 8), ("dan", "Dan Levi", 8), ("noa", "Noa Katz", 6)]

# Two-week sprints. 1-4 are closed history, 5 is in flight, 6 is next.
SPRINTS = [
    ("TEAM Sprint 1", "2026-07-20", "2026-08-02", "Stand up the orders service"),
    ("TEAM Sprint 2", "2026-08-03", "2026-08-16", "Refunds and order history"),
    ("TEAM Sprint 3", "2026-08-17", "2026-08-30", "Harden the public order API"),
    ("TEAM Sprint 4", "2026-08-31", "2026-09-13", "Payment reliability"),
    ("TEAM Sprint 5", "2026-09-14", "2026-09-27", "Fast order reads"),
    ("TEAM Sprint 6", "2026-09-28", "2026-10-11", ""),
]

# (summary, type, points, assignee, sprints it sat in, sprint it was finished
# in -- or the status it is in now). Created in this order, so the first is
# TEAM-1, the key the GitLab demo branch carries.
#
# TEAM-6 and TEAM-9 spill over: unfinished when their first sprint closed,
# done in the next. Jira keeps both sprints on the issue, which is exactly the
# case that inflates a naive velocity count.
#
# Only Stories carry points: the default scrum setup does not allow story
# points on Bugs or Tasks, so those stay unestimated -- as on most real boards.
ISSUES: list[tuple[str, str, float | None, str, list[int], int | str]] = [
    ("Cache order reads", "Story", 5, "maya", [5], "In Progress"),
    ("Set up orders service skeleton", "Story", 3, "dan", [1], 1),
    ("Validate order totals", "Story", 2, "noa", [1], 1),
    ("Order history endpoint", "Story", 5, "maya", [1], 1),
    ("Paginate order history", "Story", 3, "dan", [2], 2),
    ("Refund API", "Story", 8, "maya", [2, 3], 3),
    ("Fix rounding in order totals", "Bug", None, "noa", [2], 2),
    ("Audit log for order changes", "Story", 3, "dan", [2], 2),
    ("Rate-limit the public order API", "Story", 5, "noa", [3, 4], 4),
    ("Split OrderService into reader and writer", "Story", 3, "maya", [3], 3),
    ("Export orders as CSV", "Story", 2, "dan", [3], 3),
    ("Retry failed payment webhooks", "Story", 5, "dan", [4], 4),
    ("Order status notifications", "Story", 3, "noa", [4], 4),
    ("Upgrade the database driver", "Story", 2, "maya", [4], 4),
    ("Invalidate cache on order update", "Story", 3, "maya", [5], "To Do"),
    ("Load-test order reads", "Story", 3, "dan", [5], "In Progress"),
    ("Customer order search", "Story", 5, "noa", [5], "Done"),
    ("Flaky test in the checkout suite", "Bug", None, "dan", [5], "To Do"),
    ("Multi-currency order totals", "Story", 8, "", [], "To Do"),
    ("Nightly order archival job", "Story", 5, "", [], "To Do"),
    ("GraphQL order query", "Story", None, "", [], "To Do"),
    ("Admin order dashboard", "Story", 5, "", [], "To Do"),
    ("Retire the legacy v1 order endpoint", "Story", 3, "", [], "To Do"),
    ("Improve order API docs", "Task", None, "", [], "To Do"),
]


def seed_jira() -> dict[str, object]:
    token = env("JIRA_PAT")
    if not token:
        raise SystemExit(f"JIRA_PAT is empty in {ENV}")
    auth = {"Authorization": f"Bearer {token}"}
    api = lambda method, path, body=None: call(method, JIRA + path, auth, body)  # noqa: E731

    # People -- only the display name matters to DonnyT; nobody logs in as them.
    for name, display, _ in PEOPLE:
        if api("GET", f"/rest/api/2/user?username={name}")[0] != 200:
            ok(api("POST", "/rest/api/2/user", {
                "name": name, "displayName": display, "emailAddress": f"{name}@devstack.local",
                "password": "Unused-" + token[:12], "applicationKeys": ["jira-software"],
            }), f"create user {name}")
    print(f"  users: {', '.join(d for _, d, _ in PEOPLE)}")

    # Start from a clean project so a re-run gives the same history.
    if api("GET", f"/rest/api/2/project/{KEY}")[0] == 200:
        for board in (api("GET", f"/rest/agile/1.0/board?projectKeyOrId={KEY}")[1] or {}).get("values", []):
            api("DELETE", f"/rest/agile/1.0/board/{board['id']}")
        ok(api("DELETE", f"/rest/api/2/project/{KEY}"), "delete old project")
        print(f"  removed the previous {KEY} project")
    ok(api("POST", "/rest/api/2/project", {
        "key": KEY, "name": "Team Orders", "lead": "admin",
        "projectTypeKey": "software",
        "projectTemplateKey": "com.pyxis.greenhopper.jira:gh-scrum-template",
    }), "create project")

    roles = ok(api("GET", f"/rest/api/2/project/{KEY}/role"), "list roles")
    for role, url in roles.items():
        if role != "Administrators":
            path = urllib.parse.urlparse(url).path
            api("POST", path, {"user": [n for n, _, _ in PEOPLE]})

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

    # Issues, then estimates through the agile API: it writes to whatever field
    # the board estimates with, whether or not that field is on the screen.
    keys: list[str] = []
    for summary, kind, pts, who, _, _ in ISSUES:
        fields_ = {"project": {"key": KEY}, "summary": summary, "issuetype": {"name": kind}}
        if who:
            fields_["assignee"] = {"name": who}
        created = ok(api("POST", "/rest/api/2/issue", {"fields": fields_}), f"create {summary!r}")
        keys.append(created["key"])
        if pts is not None:
            ok(api("PUT", f"/rest/agile/1.0/issue/{created['key']}/estimation?boardId={board}",
                   {"value": str(pts)}), f"estimate {created['key']}")
    print(f"  issues: {keys[0]} .. {keys[-1]} ({len(keys)})")

    def move(key: str, status: str) -> None:
        options = ok(api("GET", f"/rest/api/2/issue/{key}/transitions"), f"transitions {key}")
        match = next((t for t in options["transitions"] if t["to"]["name"] == status), None)
        if match:
            ok(api("POST", f"/rest/api/2/issue/{key}/transitions", {"transition": {"id": match["id"]}}),
               f"move {key} to {status}")

    # Replay the history sprint by sprint: fill it, start it, finish what was
    # finished in it, close it.
    for n, (name, start, end, goal) in enumerate(SPRINTS, 1):
        sprint = ok(api("POST", "/rest/agile/1.0/sprint", {
            "name": name, "originBoardId": board, "goal": goal,
            "startDate": f"{start}T09:00:00.000+03:00", "endDate": f"{end}T18:00:00.000+03:00",
        }), f"create {name}")
        members = [keys[i] for i, issue in enumerate(ISSUES) if n in issue[4]]
        if members:
            ok(api("POST", f"/rest/agile/1.0/sprint/{sprint['id']}/issue", {"issues": members}), f"fill {name}")
        if n > 5:
            print(f"  {name}: future, empty")
            continue
        ok(api("POST", f"/rest/agile/1.0/sprint/{sprint['id']}", {
            "state": "active",
            "startDate": f"{start}T09:00:00.000+03:00", "endDate": f"{end}T18:00:00.000+03:00",
        }), f"start {name}")
        for i, issue in enumerate(ISSUES):
            outcome = issue[5]
            if outcome == n or (n == 5 and n in issue[4] and isinstance(outcome, str)):
                target = "Done" if outcome == n else outcome
                if target != "To Do":
                    if target == "Done":
                        move(keys[i], "In Progress")
                    move(keys[i], target)
        if n < 5:
            ok(api("POST", f"/rest/agile/1.0/sprint/{sprint['id']}", {"state": "closed"}), f"close {name}")
        state = "closed" if n < 5 else "active"
        print(f"  {name}: {state}, {len(members)} issues")

    return {"board": board, "points": points}


# ------------------------------------------------------------ confluence

CONFLUENCE = "http://127.0.0.1:8090"
SPACE = "ENG"
TEMPLATE_TITLE = "Merge Request Template"

# Written the way real teams write templates: a callout, placeholders, a
# status macro in a table, a task list, an expand and a warning. Each of these
# is a different macro shape for the Markdown converter to get right.
TEMPLATE = """\
<ac:structured-macro ac:name="info"><ac:rich-text-body><p>Copy this template into every merge request. Keep every heading; if a section does not apply, write N/A and say why.</p></ac:rich-text-body></ac:structured-macro>
<h2>Summary</h2>
<p><ac:placeholder>What does this MR change, in one or two sentences?</ac:placeholder></p>
<h2>Jira issue</h2>
<p><ac:placeholder>Link the issue, e.g. TEAM-123.</ac:placeholder></p>
<h2>Why</h2>
<p><ac:placeholder>The problem this solves, or the decision behind it.</ac:placeholder></p>
<h2>What changed</h2>
<ul><li><ac:placeholder>The main change, concretely.</ac:placeholder></li></ul>
<h2>Risk</h2>
<table><tbody>
<tr><th>Area</th><th>Risk</th><th>Mitigation</th></tr>
<tr><td>Database</td><td><ac:structured-macro ac:name="status"><ac:parameter ac:name="colour">Green</ac:parameter><ac:parameter ac:name="title">Low</ac:parameter></ac:structured-macro></td><td><ac:placeholder>Migrations, locks, backfills.</ac:placeholder></td></tr>
<tr><td>API</td><td><ac:structured-macro ac:name="status"><ac:parameter ac:name="colour">Yellow</ac:parameter><ac:parameter ac:name="title">Medium</ac:parameter></ac:structured-macro></td><td><ac:placeholder>Breaking changes, versioning.</ac:placeholder></td></tr>
</tbody></table>
<h2>Testing</h2>
<ac:task-list>
<ac:task><ac:task-id>1</ac:task-id><ac:task-status>incomplete</ac:task-status><ac:task-body>Unit tests added or updated</ac:task-body></ac:task>
<ac:task><ac:task-id>2</ac:task-id><ac:task-status>incomplete</ac:task-status><ac:task-body>Tested locally against a real database</ac:task-body></ac:task>
<ac:task><ac:task-id>3</ac:task-id><ac:task-status>incomplete</ac:task-status><ac:task-body>No new warnings in CI</ac:task-body></ac:task>
</ac:task-list>
<h2>Rollout</h2>
<ac:structured-macro ac:name="expand"><ac:parameter ac:name="title">Rollout checklist</ac:parameter><ac:rich-text-body><ul><li>Behind a feature flag, or safe to ship dark</li><li>Migration order written down</li><li>Rollback plan</li></ul></ac:rich-text-body></ac:structured-macro>
<ac:structured-macro ac:name="warning"><ac:rich-text-body><p>Anything touching auth, payments or data deletion needs a second reviewer.</p></ac:rich-text-body></ac:structured-macro>
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

    template_id = upsert(TEMPLATE_TITLE, TEMPLATE)
    plans_id = upsert("Sprint Plans", "<p>Sprint plans published by DonnyT live under this page.</p>")
    print(f"  space {SPACE}: template page {template_id}, sprint plans page {plans_id}")
    return {"template": template_id, "plans": plans_id}


# ------------------------------------------------------------ donnyt config

CONFIG = HERE / "donnyt" / "config.toml"


def write_config(jira: dict[str, object] | None, confluence: dict[str, object] | None) -> None:
    """Point the devstack's DonnyT config at what was just created."""
    import re

    text = CONFIG.read_text(encoding="utf-8")

    def setting(key: str, value: str) -> None:
        nonlocal text
        text = re.sub(rf"(?m)^{key}\s*=.*$", f"{key} = {value}", text, count=1)

    if jira:
        setting("board_id", str(jira["board"]))
        if jira["points"]:
            setting("story_points_field", f'"{jira["points"]}"')
        text = re.sub(r"(?ms)^\[\[team\.members\]\].*", "", text).rstrip() + "\n\n" + "\n".join(
            f'[[team.members]]\nname = "{display}"\njira = "{name}"\ngitlab = ""\ncapacity = {cap}\n'
            for name, display, cap in PEOPLE
        )
    if confluence:
        setting("mr_template_page_id", f'"{confluence["template"]}"')
        if "sprint_plan_parent_page_id" in text:
            setting("sprint_plan_parent_page_id", f'"{confluence["plans"]}"')
        else:
            text = text.replace(
                "[confluence]\n", f'[confluence]\nsprint_plan_parent_page_id = "{confluence["plans"]}"\n', 1
            )
    CONFIG.write_text(text, encoding="utf-8")
    print(f"donnyt: updated {CONFIG.relative_to(HERE.parent.parent)}")


SEEDERS = {"gitlab": seed_gitlab, "jira": seed_jira, "confluence": seed_confluence}


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
