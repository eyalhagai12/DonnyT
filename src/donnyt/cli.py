"""Command line interface.

Pure standard library, so this works on an isolated host even when no packages
could be installed at all. Every MCP tool has a CLI equivalent here.

    python -m donnyt.cli doctor
    python -m donnyt.cli template
    python -m donnyt.cli velocity --sprints-back 5
    python -m donnyt.cli sync --sprints-back 3
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from .config import ConfigError


def _print(data: Any, as_json: bool = True) -> None:
    if as_json:
        print(json.dumps(data, indent=2, ensure_ascii=False, default=str))
    else:
        print(data)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="donnyt",
        description="Team-lead toolkit: Confluence templates, Jira sprints, GitLab MRs, Obsidian graph.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", help="Check configuration and connectivity.")
    sub.add_parser("template", help="Print the Confluence MR template as Markdown.")

    page = sub.add_parser("page", help="Print a Confluence page as Markdown.")
    page.add_argument("page_id")

    search = sub.add_parser("search", help="Search Confluence with CQL.")
    search.add_argument("cql")
    search.add_argument("--limit", type=int, default=25)

    jql = sub.add_parser("jql", help="Run a Jira JQL query.")
    jql.add_argument("query")
    jql.add_argument("--limit", type=int, default=50)

    sprints = sub.add_parser("sprints", help="List sprints on the configured board.")
    sprints.add_argument("--state", default="", choices=["", "active", "future", "closed"])

    backlog = sub.add_parser("backlog", help="Board backlog in rank order.")
    backlog.add_argument("--limit", type=int, default=60)

    velocity = sub.add_parser("velocity", help="Completed points per recent sprint.")
    velocity.add_argument("--sprints-back", type=int, default=5)

    workload = sub.add_parser("workload", help="Points per assignee versus capacity.")
    workload.add_argument("--sprint-id", type=int, default=0)

    mrs = sub.add_parser("mrs", help="List GitLab merge requests.")
    mrs.add_argument("--state", default="opened")
    mrs.add_argument("--limit", type=int, default=30)

    branch = sub.add_parser("branch", help="Summarize a local branch against its target.")
    branch.add_argument("repo_path")
    branch.add_argument("--target", default="")

    sync = sub.add_parser("sync", help="Pull Jira and GitLab into the Obsidian vault.")
    sync.add_argument("--sprints-back", type=int, default=3)
    sync.add_argument("--no-mrs", action="store_true")

    vault_search = sub.add_parser("vault-search", help="Full-text search the vault.")
    vault_search.add_argument("query")
    vault_search.add_argument("--limit", type=int, default=30)

    vault_links = sub.add_parser("vault-links", help="Inbound and outbound links for a note.")
    vault_links.add_argument("title")

    sub.add_parser("vault-stats", help="Note counts per type.")
    sub.add_parser("serve", help="Run the MCP server over stdio (as Claude Code does).")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        return _dispatch(args)
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
        from .doctor import format_report, run_checks

        report = run_checks()
        print(format_report(report))
        return 0 if report["ok"] else 1

    if command == "serve":
        from .mcp_server import main as serve

        serve()
        return 0

    if command == "template":
        from .graph import fetch_mr_template

        result = fetch_mr_template()
        print(f"# Source: {result['page']['title']}  ({result['page']['url']})\n")
        print(result["markdown"])
        return 0

    if command == "page":
        from .confluence import ConfluenceClient

        print(ConfluenceClient().get_page(args.page_id).markdown)
        return 0

    if command == "search":
        from .confluence import ConfluenceClient

        _print(ConfluenceClient().search(args.cql, args.limit))
        return 0

    if command in {"jql", "sprints", "backlog", "velocity", "workload"}:
        return _jira_command(args)

    if command in {"mrs", "branch"}:
        return _gitlab_command(args)

    return _vault_command(args)


def _jira_command(args: argparse.Namespace) -> int:
    from .jira import JiraClient

    jira = JiraClient()
    command = args.command

    if command == "jql":
        _print([i.as_dict() for i in jira.search(args.query, args.limit)])
    elif command == "sprints":
        _print([s.as_dict() for s in jira.sprints(state=args.state or None)])
    elif command == "backlog":
        _print([i.as_dict() for i in jira.backlog(limit=args.limit)])
    elif command == "velocity":
        _print(jira.velocity(sprints_back=args.sprints_back))
    elif command == "workload":
        sprint_id = args.sprint_id
        if not sprint_id:
            active = jira.active_sprint()
            if not active:
                print("No active sprint on this board.", file=sys.stderr)
                return 1
            sprint_id = active.id
        _print(jira.workload(sprint_id))
    return 0


def _gitlab_command(args: argparse.Namespace) -> int:
    if args.command == "mrs":
        from .gitlab import GitLabClient

        _print(
            [
                mr.as_dict()
                for mr in GitLabClient().list_merge_requests(state=args.state, limit=args.limit)
            ]
        )
    else:
        from .config import load_config
        from .gitlab import local_branch_summary

        _print(local_branch_summary(args.repo_path, args.target or load_config().gitlab_target_branch))
    return 0


def _vault_command(args: argparse.Namespace) -> int:
    from .vault import Vault

    if args.command == "sync":
        from .graph import GraphBuilder

        _print(GraphBuilder().sync_all(args.sprints_back, not args.no_mrs))
    elif args.command == "vault-search":
        _print(Vault().search(args.query, args.limit))
    elif args.command == "vault-links":
        vault = Vault()
        _print({"backlinks": vault.backlinks(args.title), "outlinks": vault.outlinks(args.title)})
    elif args.command == "vault-stats":
        _print(Vault().stats())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
