"""Act as a member of the simulated team on the devstack.

DonnyT is the team lead's toolkit. This is everyone else: the engineers who
write the code, push branches, open and review merge requests, and move their
tickets. Claude uses it to play the team through a sprint -- see SIMULATION.md.
DonnyT only reads what they leave behind in GitLab.

    python test/devstack/team.py clone
    python test/devstack/team.py commit --as maya -m "TEAM-11 Return todos oldest first"
    python test/devstack/team.py push --as maya TEAM-11-list-order
    python test/devstack/team.py mr --as maya TEAM-11-list-order --title "..." --file desc.md
    python test/devstack/team.py review --as omer 3 --note "Looks good" --approve
    python test/devstack/team.py merge --as omer 3
    python test/devstack/team.py move TEAM-11 Done
    python test/devstack/team.py start-sprint 4
    python test/devstack/team.py close-sprint 4 --to 5
    python test/devstack/team.py new-issue "Export todos as CSV" --description "..."

GitLab actions use each person's own token (written by seed.py), so commits,
MRs, reviews and merges carry their names. Jira actions go through the admin
token: DonnyT only reads who an issue is assigned to, not who moved it.

Stdlib only, like the toolkit itself.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from seed import (
    GITLAB_WEB, HERE, JIRA, KEY, NAMES, PROJECT, REPOS, TOKENS, call, env, git, ok, project_url,
)

# The repo being worked in: team/todo unless --repo says otherwise. Each has
# its own working copy under donnyt/work/, named after the project.
REPO = PROJECT
WORK = HERE / "donnyt" / "work" / PROJECT.split("/")[-1]


def use_repo(project: str) -> None:
    global REPO, WORK
    known = [r for r, *_ in REPOS]
    if project not in known:
        raise SystemExit(f"{project!r} is not a devstack repo: {', '.join(known)}")
    REPO, WORK = project, HERE / "donnyt" / "work" / project.split("/")[-1]


def token(login: str) -> str:
    if login not in NAMES:
        raise SystemExit(f"{login!r} is not on the team: {', '.join(NAMES)}")
    if not TOKENS.exists():
        raise SystemExit(f"{TOKENS} is missing; run `python test/devstack/seed.py gitlab` first.")
    return json.loads(TOKENS.read_text(encoding="utf-8"))[login]


def gitlab(login: str, method: str, path: str, body: object = None) -> object:
    return ok(call(method, project_url(REPO) + path, {"PRIVATE-TOKEN": token(login)}, body),
              f"{method} {path} as {login}")


def remote(login: str | None = None) -> str:
    """The repo URL with a token in it: the person's, or the admin's for reading."""
    secret = token(login) if login else env("GITLAB_TOKEN")
    return f"http://{login or 'root'}:{secret}@{GITLAB_WEB.removeprefix('http://')}/{REPO}.git"


def jira(method: str, path: str, body: object = None) -> object:
    return ok(call(method, JIRA + path, {"Authorization": f"Bearer {env('JIRA_PAT')}"}, body),
              f"{method} {path}")


def identity(login: str) -> dict[str, str]:
    name, email = NAMES[login], f"{login}@devstack.local"
    return {"GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email,
            "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": email}


# -- git -------------------------------------------------------------------


def cmd_clone(a: argparse.Namespace) -> None:
    """A working copy at donnyt/work/todo, reset to GitLab's main."""
    if not (WORK / ".git").exists():
        WORK.parent.mkdir(parents=True, exist_ok=True)
        git("clone", "-q", remote(), str(WORK), cwd=WORK.parent)
    git("fetch", "-q", "--prune", remote(), "+refs/heads/*:refs/remotes/origin/*", cwd=WORK)
    git("checkout", "-q", "main", cwd=WORK)
    git("reset", "-q", "--hard", "origin/main", cwd=WORK)
    git("clean", "-q", "-fd", cwd=WORK)
    # A reset means a reset: last sprint's local branches go too.
    for branch in git("branch", "--format=%(refname:short)", cwd=WORK).split():
        if branch != "main":
            git("branch", "-q", "-D", branch, cwd=WORK)
    print(f"{WORK} at {git('log', '--oneline', '-1', cwd=WORK).strip()}")


def cmd_commit(a: argparse.Namespace) -> None:
    """Commit everything in the working copy as that person."""
    git("add", "-A", cwd=WORK)
    git("commit", "-q", "-m", a.message, cwd=WORK, env_=identity(a.as_))
    print(git("log", "--format=%h %an: %s", "-1", cwd=WORK).strip())


def cmd_push(a: argparse.Namespace) -> None:
    # Pushes go to a token URL, so there is no remote-tracking ref for
    # --force-with-lease to check; a rewrite has to be asked for.
    force = ["--force"] if a.force else []
    git("push", "-q", *force, remote(a.as_), f"{a.branch}:{a.branch}", cwd=WORK)
    print(f"pushed {a.branch} as {a.as_}" + (" (forced)" if a.force else ""))


# -- merge requests --------------------------------------------------------


def cmd_mr(a: argparse.Namespace) -> None:
    description = Path(a.file).read_text(encoding="utf-8") if a.file else ""
    mr = gitlab(a.as_, "POST", "/merge_requests", {
        "source_branch": a.branch, "target_branch": a.target,
        "title": ("Draft: " if a.draft else "") + a.title,
        "description": description, "remove_source_branch": True,
    })
    print(f"!{mr['iid']} by {mr['author']['username']}: {mr['web_url']}")


def cmd_review(a: argparse.Namespace) -> None:
    if a.note:
        gitlab(a.as_, "POST", f"/merge_requests/{a.iid}/notes", {"body": a.note})
    if a.approve:
        gitlab(a.as_, "POST", f"/merge_requests/{a.iid}/approve")
    print(f"!{a.iid} reviewed by {a.as_}" + (" (approved)" if a.approve else ""))


def cmd_merge(a: argparse.Namespace) -> None:
    mr = gitlab(a.as_, "GET", f"/merge_requests/{a.iid}")
    if mr.get("draft") or mr.get("work_in_progress"):
        gitlab(a.as_, "PUT", f"/merge_requests/{a.iid}",
               {"title": mr["title"].removeprefix("Draft:").strip()})
    # GitLab works out mergeability in the background; give it a moment.
    for _ in range(20):
        status = gitlab(a.as_, "GET", f"/merge_requests/{a.iid}").get("detailed_merge_status", "")
        if status not in ("checking", "unchecked", "preparing", "approvals_syncing"):
            break
        time.sleep(1)
    merged = gitlab(a.as_, "PUT", f"/merge_requests/{a.iid}/merge",
                    {"should_remove_source_branch": True})
    print(f"!{a.iid} merged by {a.as_} as {merged.get('merge_commit_sha', '')[:8]}")


# -- jira ------------------------------------------------------------------


def transition(key: str, status: str) -> bool:
    options = jira("GET", f"/rest/api/2/issue/{key}/transitions")["transitions"]
    match = next((t for t in options if t["to"]["name"].lower() == status.lower()), None)
    if match:
        jira("POST", f"/rest/api/2/issue/{key}/transitions", {"transition": {"id": match["id"]}})
    return match is not None


def cmd_move(a: argparse.Namespace) -> None:
    # A workflow may not allow To Do -> Done directly; go through In Progress.
    if not transition(a.key, a.status):
        if not (transition(a.key, "In Progress") and transition(a.key, a.status)):
            raise SystemExit(f"No transition to {a.status!r} from where {a.key} is now.")
    print(f"{a.key} -> {a.status}")


def cmd_start_sprint(a: argparse.Namespace) -> None:
    sprint = jira("GET", f"/rest/agile/1.0/sprint/{a.sprint_id}")
    if not (sprint.get("startDate") and sprint.get("endDate")):
        raise SystemExit(f"Sprint {a.sprint_id} has no dates; set them with DonnyT's update-sprint first.")
    jira("POST", f"/rest/agile/1.0/sprint/{a.sprint_id}",
         {"state": "active", "startDate": sprint["startDate"], "endDate": sprint["endDate"]})
    print(f"{sprint['name']} started")


def cmd_close_sprint(a: argparse.Namespace) -> None:
    """Close a sprint, then carry unfinished work into the next one -- in that
    order, as Jira's own "Complete sprint" does, so each issue remembers the
    sprint it spilled out of."""
    issues = jira("GET", f"/rest/agile/1.0/sprint/{a.sprint_id}/issue?fields=status&maxResults=200")["issues"]
    open_ = [i["key"] for i in issues if i["fields"]["status"]["statusCategory"]["key"] != "done"]
    jira("POST", f"/rest/agile/1.0/sprint/{a.sprint_id}", {"state": "closed"})
    if open_ and a.to:
        jira("POST", f"/rest/agile/1.0/sprint/{a.to}/issue", {"issues": open_})
    elif open_:
        jira("POST", "/rest/agile/1.0/backlog/issue", {"issues": open_})
    where = f"sprint {a.to}" if a.to else "the backlog"
    print(f"sprint {a.sprint_id} closed; {len(issues) - len(open_)} done, "
          f"{len(open_)} carried to {where}{': ' + ', '.join(open_) if open_ else ''}")


def cmd_new_issue(a: argparse.Namespace) -> None:
    fields: dict[str, object] = {"project": {"key": KEY}, "summary": a.summary,
                                 "issuetype": {"name": a.type}, "description": a.description}
    if a.assign:
        fields["assignee"] = {"name": a.assign}
    created = jira("POST", "/rest/api/2/issue", {"fields": fields})
    print(f"{created['key']} {a.summary}")


# -- cli -------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="team.py", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    def as_(p: argparse.ArgumentParser) -> argparse.ArgumentParser:
        p.add_argument("--as", dest="as_", required=True, choices=list(NAMES), help="Who does it.")
        return p

    sub.add_parser("clone", help="Clone or reset the working copy to GitLab's main.")
    commit = as_(sub.add_parser("commit", help="Commit all changes in the working copy as someone."))
    commit.add_argument("-m", "--message", required=True)
    push = as_(sub.add_parser("push", help="Push a branch as someone."))
    push.add_argument("branch")
    push.add_argument("--force", action="store_true", help="Overwrite the remote branch (after a rebase).")
    mr = as_(sub.add_parser("mr", help="Open a merge request as someone."))
    mr.add_argument("branch")
    mr.add_argument("--title", required=True)
    mr.add_argument("--file", default="", help="Description Markdown.")
    mr.add_argument("--target", default="main")
    mr.add_argument("--draft", action="store_true")
    review = as_(sub.add_parser("review", help="Comment on and/or approve a merge request."))
    review.add_argument("iid", type=int)
    review.add_argument("--note", default="")
    review.add_argument("--approve", action="store_true")
    merge = as_(sub.add_parser("merge", help="Merge a merge request as someone."))
    merge.add_argument("iid", type=int)
    move = sub.add_parser("move", help="Move a Jira issue to a status, e.g. 'In Progress' or Done.")
    move.add_argument("key")
    move.add_argument("status")
    start = sub.add_parser("start-sprint", help="Start a planned sprint.")
    start.add_argument("sprint_id", type=int)
    close = sub.add_parser("close-sprint", help="Close a sprint; unfinished work moves on.")
    close.add_argument("sprint_id", type=int)
    close.add_argument("--to", type=int, default=0, help="Next sprint id; default is the backlog.")
    new = sub.add_parser("new-issue", help="Create a ticket, e.g. one cut from a PRD.")
    new.add_argument("summary")
    new.add_argument("--type", default="Story", choices=["Story", "Bug", "Task"])
    new.add_argument("--description", default="")
    new.add_argument("--assign", default="", choices=["", *NAMES])

    parser.add_argument("--repo", default=PROJECT,
                        help=f"GitLab project to work in (default {PROJECT}); put it before the command.")
    args = parser.parse_args(argv)
    use_repo(args.repo)
    handler = globals()["cmd_" + args.command.replace("-", "_")]
    handler(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
