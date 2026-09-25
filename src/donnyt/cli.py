"""Command line interface.

Pure standard library, so this works on an isolated host even when no packages
could be installed at all. Every MCP tool has a CLI equivalent here -- both
call :mod:`donnyt.ops` -- and ``donnyt tools`` prints the mapping, so a skill
written against MCP tool names can be followed from a shell instead.

    python -m donnyt.cli doctor
    python -m donnyt.cli template
    python -m donnyt.cli velocity --sprints-back 5
    python -m donnyt.cli sync --sprints-back 3

Long Markdown arguments (MR descriptions, pages, notes) are read from a file,
or from stdin when the path is ``-``, so nothing has to survive shell quoting.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import ops
from .config import ConfigError

# MCP tool -> CLI command. Kept next to the parser so a new tool without a
# command is obvious; `donnyt tools` prints it.
TOOLS: dict[str, str] = {
    "confluence_get_mr_template": "template [--raw]",
    "confluence_get_page": "page PAGE_ID [--raw]",
    "confluence_search": "search CQL [--limit N]",
    "confluence_publish": "publish TITLE --file PATH [--parent-id ID]",
    "jira_search": "jql QUERY [--limit N]",
    "jira_get_issue": "issue KEY",
    "jira_sprints": "sprints [--state active|future|closed]",
    "jira_sprint_issues": "sprint-issues [--sprint-id N]",
    "jira_backlog": "backlog [--limit N]",
    "jira_velocity": "velocity [--sprints-back N]",
    "jira_workload": "workload [--sprint-id N]",
    "jira_create_sprint": "create-sprint NAME [--start D] [--end D] [--goal TEXT]",
    "jira_add_to_sprint": "add-to-sprint SPRINT_ID KEY [KEY ...]",
    "gitlab_branch_summary": "branch REPO_PATH [--target BRANCH]",
    "gitlab_compare": "compare SOURCE [--target BRANCH] [--project P]",
    "gitlab_list_mrs": "mrs [--state S] [--author USER] [--limit N]",
    "gitlab_create_mr": "create-mr SOURCE_BRANCH --title T --file PATH [--ready] [--label L ...]",
    "gitlab_update_mr": "update-mr IID [--title T] [--file PATH] [--label L ...]",
    "vault_search": "vault-search QUERY [--limit N]",
    "vault_read": "vault-read TITLE",
    "vault_links": "vault-links TITLE",
    "vault_stats": "vault-stats",
    "vault_write_note": "vault-write TITLE --kind K --file PATH [--tag T ...] [--link TITLE ...]",
    "vault_record_decision": "record-decision TITLE --context C --decision D [--person P ...]",
    "vault_sync": "sync [--sprints-back N] [--no-mrs]",
    "vault_sync_sprint": "sync-sprint [--sprint-id N]",
    "vault_sync_mr": "sync-mr IID [--project P] [--summary TEXT]",
    "donnyt_doctor": "doctor",
}


def _print(data: Any) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False, default=str))


def _read_text(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    return Path(path).read_text(encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="donnyt",
        description="Team-lead toolkit: Confluence templates, Jira sprints, GitLab MRs, Obsidian graph.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # -- meta --------------------------------------------------------------
    sub.add_parser("doctor", help="Check configuration and connectivity.")
    sub.add_parser("tools", help="Map each MCP tool name to its CLI command.")
    sub.add_parser("serve", help="Run the MCP server over stdio (as Claude Code does).")

    # -- confluence --------------------------------------------------------
    template = sub.add_parser("template", help="Print the Confluence MR template as Markdown.")
    template.add_argument(
        "--raw",
        action="store_true",
        help="Print the raw Confluence storage-format XHTML instead of the converted Markdown. "
        "Use this to diagnose a section that converted wrong or went missing.",
    )

    page = sub.add_parser("page", help="Print a Confluence page as Markdown.")
    page.add_argument("page_id")
    page.add_argument(
        "--raw",
        action="store_true",
        help="Print the raw Confluence storage-format XHTML instead of the converted Markdown.",
    )

    search = sub.add_parser("search", help="Search Confluence with CQL.")
    search.add_argument("cql")
    search.add_argument("--limit", type=int, default=25)

    publish = sub.add_parser(
        "publish", help="Create or update a Confluence page from a Markdown file. Team-visible."
    )
    publish.add_argument("title")
    publish.add_argument("--file", required=True, help="Markdown file, or - for stdin.")
    publish.add_argument("--parent-id", default="")

    # -- jira --------------------------------------------------------------
    jql = sub.add_parser("jql", help="Run a Jira JQL query.")
    jql.add_argument("query")
    jql.add_argument("--limit", type=int, default=50)

    issue = sub.add_parser("issue", help="Fetch one Jira issue by key.")
    issue.add_argument("key")

    sprints = sub.add_parser("sprints", help="List sprints on the configured board.")
    sprints.add_argument("--state", default="", choices=["", "active", "future", "closed"])

    sprint_issues = sub.add_parser("sprint-issues", help="Issues in a sprint (default: active).")
    sprint_issues.add_argument("--sprint-id", type=int, default=0)

    backlog = sub.add_parser("backlog", help="Board backlog in rank order.")
    backlog.add_argument("--limit", type=int, default=60)

    velocity = sub.add_parser("velocity", help="Completed points per recent sprint.")
    velocity.add_argument("--sprints-back", type=int, default=5)

    workload = sub.add_parser("workload", help="Points per assignee versus capacity.")
    workload.add_argument("--sprint-id", type=int, default=0)

    create_sprint = sub.add_parser("create-sprint", help="Create a sprint on the board. Team-visible.")
    create_sprint.add_argument("name")
    create_sprint.add_argument("--start", default="", help="YYYY-MM-DD")
    create_sprint.add_argument("--end", default="", help="YYYY-MM-DD")
    create_sprint.add_argument("--goal", default="")

    add_to_sprint = sub.add_parser("add-to-sprint", help="Move issues into a sprint. Team-visible.")
    add_to_sprint.add_argument("sprint_id", type=int)
    add_to_sprint.add_argument("keys", nargs="+")

    # -- gitlab ------------------------------------------------------------
    branch = sub.add_parser("branch", help="Summarize a local branch against its target.")
    branch.add_argument("repo_path")
    branch.add_argument("--target", default="")

    compare = sub.add_parser("compare", help="Compare two refs on the GitLab server.")
    compare.add_argument("source")
    compare.add_argument("--target", default="")
    compare.add_argument("--project", default="")

    mrs = sub.add_parser("mrs", help="List GitLab merge requests.")
    mrs.add_argument("--state", default="opened")
    mrs.add_argument("--author", default="")
    mrs.add_argument("--limit", type=int, default=30)

    create_mr = sub.add_parser("create-mr", help="Open a merge request (draft by default). Team-visible.")
    create_mr.add_argument("source_branch")
    create_mr.add_argument("--title", required=True)
    create_mr.add_argument("--file", required=True, help="Description Markdown file, or - for stdin.")
    create_mr.add_argument("--target", default="")
    create_mr.add_argument("--project", default="")
    create_mr.add_argument("--ready", action="store_true", help="Open as ready, not draft.")
    create_mr.add_argument("--label", action="append", default=None)

    update_mr = sub.add_parser("update-mr", help="Update an MR's title, description or labels.")
    update_mr.add_argument("iid", type=int)
    update_mr.add_argument("--title", default="")
    update_mr.add_argument("--file", default="", help="New description file, or - for stdin.")
    update_mr.add_argument("--project", default="")
    update_mr.add_argument("--label", action="append", default=None)

    # -- vault -------------------------------------------------------------
    sync = sub.add_parser("sync", help="Pull Jira and GitLab into the Obsidian vault.")
    sync.add_argument("--sprints-back", type=int, default=3)
    sync.add_argument("--no-mrs", action="store_true")

    sync_sprint = sub.add_parser("sync-sprint", help="Write one sprint's vault note.")
    sync_sprint.add_argument("--sprint-id", type=int, default=0)

    sync_mr = sub.add_parser("sync-mr", help="Write one merge request's vault note.")
    sync_mr.add_argument("iid", type=int)
    sync_mr.add_argument("--project", default="")
    sync_mr.add_argument("--summary", default="")

    vault_search = sub.add_parser("vault-search", help="Full-text search the vault.")
    vault_search.add_argument("query")
    vault_search.add_argument("--limit", type=int, default=30)

    vault_read = sub.add_parser("vault-read", help="Read a vault note by title.")
    vault_read.add_argument("title")

    vault_links = sub.add_parser("vault-links", help="Inbound and outbound links for a note.")
    vault_links.add_argument("title")

    sub.add_parser("vault-stats", help="Note counts per type.")

    vault_write = sub.add_parser("vault-write", help="Write or refresh a note, keeping hand-written prose.")
    vault_write.add_argument("title")
    vault_write.add_argument(
        "--kind", required=True,
        choices=["person", "sprint", "mr", "project", "decision", "meeting", "topic"],
    )
    vault_write.add_argument("--file", required=True, help="Markdown file, or - for stdin.")
    vault_write.add_argument("--tag", action="append", default=None)
    vault_write.add_argument("--link", action="append", default=None, help="Note title to link.")

    decision = sub.add_parser("record-decision", help="Record a team decision as an ADR note.")
    decision.add_argument("title")
    decision.add_argument("--context", required=True)
    decision.add_argument("--decision", required=True)
    decision.add_argument("--consequences", default="")
    decision.add_argument("--person", action="append", default=None)
    decision.add_argument("--related", action="append", default=None)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        return _dispatch(args)
    except ops.OpError as exc:
        print(f"{exc.code}: {exc}", file=sys.stderr)
        return 1
    except ConfigError as exc:
        print(f"Configuration problem:\n\n{exc}\n", file=sys.stderr)
        print("Run `python -m donnyt.cli doctor` for a full check.", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


def _dispatch(args: argparse.Namespace) -> int:
    command = args.command

    if command == "doctor":
        from .doctor import format_report

        report = ops.doctor()
        print(format_report(report))
        return 0 if report["ok"] else 1

    if command == "tools":
        width = max(map(len, TOOLS))
        for tool, usage in TOOLS.items():
            print(f"{tool:<{width}}  python -m donnyt.cli {usage}")
        return 0

    if command == "serve":
        from .mcp_server import main as serve

        serve()
        return 0

    # Template and page print as text: they are read, not parsed.
    if command == "template":
        result = ops.mr_template(raw=args.raw)
        page = result["page"]
        print(f"<!-- Source: {page['title']}  ({page['url']}) -->\n")
        print(result["storage"] if args.raw else result["markdown"])
        return 0

    if command == "page":
        result = ops.confluence_page(args.page_id, raw=args.raw)
        print(result["storage"] if args.raw else result["markdown"])
        return 0

    handler = _HANDLERS[command]
    _print(handler(args))
    return 0


_HANDLERS: dict[str, Any] = {
    # confluence
    "search": lambda a: ops.confluence_search(a.cql, a.limit),
    "publish": lambda a: ops.confluence_publish(a.title, _read_text(a.file), a.parent_id),
    # jira
    "jql": lambda a: ops.jira_search(a.query, a.limit),
    "issue": lambda a: ops.jira_issue(a.key),
    "sprints": lambda a: ops.jira_sprints(a.state),
    "sprint-issues": lambda a: ops.jira_sprint_issues(a.sprint_id),
    "backlog": lambda a: ops.jira_backlog(a.limit),
    "velocity": lambda a: ops.jira_velocity(a.sprints_back),
    "workload": lambda a: ops.jira_workload(a.sprint_id),
    "create-sprint": lambda a: ops.jira_create_sprint(a.name, a.start, a.end, a.goal),
    "add-to-sprint": lambda a: ops.jira_add_to_sprint(a.sprint_id, a.keys),
    # gitlab
    "branch": lambda a: ops.gitlab_branch_summary(a.repo_path, a.target),
    "compare": lambda a: ops.gitlab_compare(a.source, a.target, a.project),
    "mrs": lambda a: ops.gitlab_list_mrs(a.state, a.author, a.limit),
    "create-mr": lambda a: ops.gitlab_create_mr(
        a.source_branch, a.title, _read_text(a.file), a.target, a.project, not a.ready, a.label
    ),
    "update-mr": lambda a: ops.gitlab_update_mr(
        a.iid, _read_text(a.file) if a.file else "", a.title, a.project, a.label
    ),
    # vault
    "sync": lambda a: ops.vault_sync(a.sprints_back, not a.no_mrs),
    "sync-sprint": lambda a: ops.vault_sync_sprint(a.sprint_id),
    "sync-mr": lambda a: ops.vault_sync_mr(a.iid, a.project, a.summary),
    "vault-search": lambda a: ops.vault_search(a.query, a.limit),
    "vault-read": lambda a: ops.vault_read(a.title),
    "vault-links": lambda a: ops.vault_links(a.title),
    "vault-stats": lambda a: ops.vault_stats(),
    "vault-write": lambda a: ops.vault_write_note(a.title, a.kind, _read_text(a.file), a.tag, a.link),
    "record-decision": lambda a: ops.vault_record_decision(
        a.title, a.context, a.decision, a.consequences, a.person, a.related
    ),
}


if __name__ == "__main__":
    raise SystemExit(main())
