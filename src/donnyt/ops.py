"""Every toolkit operation, once, for both front ends.

``mcp_server.py`` and ``cli.py`` are two ways of calling the functions below.
Keeping the logic here is what guarantees the CLI can do everything the MCP
server can: on a host where the ``mcp`` package cannot be installed, the CLI is
the whole toolkit, not a read-only subset of it.

Each function takes plain arguments and returns JSON-ready data. Expected
conditions a caller can act on (no active sprint, no such note) raise
:class:`OpError` with a stable ``code``; everything else propagates.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .config import load_config


class OpError(RuntimeError):
    """An expected failure, with a machine-readable code for the model."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _active_sprint_id(jira: Any, sprint_id: int) -> int:
    if sprint_id:
        return sprint_id
    active = jira.active_sprint()
    if not active:
        raise OpError("no_active_sprint", "No active sprint on this board.")
    return active.id


# ---------------------------------------------------------------- confluence


def _template(kind: str, raw: bool) -> dict[str, Any]:
    from .confluence import ConfluenceClient

    page = ConfluenceClient().get_template(kind)
    if raw:
        return {"page": page.summary(), "storage": page.storage}
    markdown = page.markdown
    return {
        "page": page.summary(),
        "markdown": markdown,
        "sections": re.findall(r"^#{1,6}\s+(.+)$", markdown, flags=re.M),
    }


def mr_template(raw: bool = False) -> dict[str, Any]:
    return _template("mr", raw)


def prd_template(raw: bool = False) -> dict[str, Any]:
    try:
        result = _template("prd", raw)
    except LookupError as exc:
        raise OpError("no_prd_template", str(exc)) from exc
    # Where a finished PRD should be published; empty means the space root.
    result["parent_id"] = load_config().prd_parent_page_id
    return result


def confluence_page(page_id: str, raw: bool = False) -> dict[str, Any]:
    from .confluence import ConfluenceClient

    page = ConfluenceClient().get_page(page_id)
    content = page.storage if raw else page.markdown
    return {**page.summary(), ("storage" if raw else "markdown"): content}


def confluence_search(cql: str, limit: int = 25) -> list[dict[str, Any]]:
    from .confluence import ConfluenceClient

    return ConfluenceClient().search(cql, limit)


def confluence_publish(
    title: str, markdown: str, parent_id: str = "", attachments: list[str] | None = None
) -> dict[str, Any]:
    from .confluence import ConfluenceClient, attachments_title

    client = ConfluenceClient()
    # Check every file before touching the page, so a typo can't leave a
    # published page pointing at images that never arrive.
    files = [_existing_file(p) for p in attachments or []]
    # Files live on a child page, "<title> - Attachments", so the page itself
    # stays clean; its images point there. Key off the Markdown, not `files`:
    # a text-only re-publish still embeds the images uploaded earlier.
    embeds = "](attachment:" in markdown
    holder_title = attachments_title(title) if files or embeds else ""
    existing = client.find_page(title)
    parent = parent_id or client.config.sprint_plan_parent_page_id or None
    page = (
        client.update_page(existing.id, title, markdown, attachment_page=holder_title)
        if existing
        else client.create_page(title, markdown, parent_id=parent, attachment_page=holder_title)
    )
    result: dict[str, Any] = {**page.summary(), "action": "updated" if existing else "created"}
    if files:
        holder = client.attachments_page(page)
        result["attachments_page"] = holder.summary()
        result["attachments"] = [client.attach(holder.id, f) for f in files]
    return result


def _existing_file(path: str) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute() and not candidate.is_file():
        candidate = load_config().root / candidate
    if not candidate.is_file():
        raise OpError("no_such_file", f"Attachment not found: {path}")
    return candidate


# --------------------------------------------------------------------- jira


def jira_search(jql: str, limit: int = 50) -> list[dict[str, Any]]:
    from .jira import JiraClient

    return [i.as_dict() for i in JiraClient().search(jql, limit)]


def jira_issue(key: str) -> dict[str, Any]:
    from .jira import JiraClient

    return JiraClient().get_issue(key).as_dict()


def jira_sprints(state: str = "") -> list[dict[str, Any]]:
    from .jira import JiraClient

    return [s.as_dict() for s in JiraClient().sprints(state=state or None)]


def jira_sprint_issues(sprint_id: int = 0) -> dict[str, Any]:
    from .jira import JiraClient

    jira = JiraClient()
    target = _active_sprint_id(jira, sprint_id)
    return {"sprint_id": target, "issues": [i.as_dict() for i in jira.sprint_issues(target)]}


def jira_backlog(limit: int = 60) -> list[dict[str, Any]]:
    from .jira import JiraClient

    return [i.as_dict() for i in JiraClient().backlog(limit=limit)]


def jira_velocity(sprints_back: int = 5) -> dict[str, Any]:
    from .jira import JiraClient

    return JiraClient().velocity(sprints_back=sprints_back)


def jira_workload(sprint_id: int = 0) -> dict[str, Any]:
    from .jira import JiraClient

    jira = JiraClient()
    return jira.workload(_active_sprint_id(jira, sprint_id))


def jira_create_sprint(name: str, start: str = "", end: str = "", goal: str = "") -> dict[str, Any]:
    from .jira import JiraClient

    return JiraClient().create_sprint(name, start=start or None, end=end or None, goal=goal).as_dict()


def jira_add_to_sprint(sprint_id: int, issue_keys: list[str]) -> dict[str, Any]:
    from .jira import JiraClient

    return JiraClient().move_issues_to_sprint(sprint_id, issue_keys)


def jira_update_sprint(
    sprint_id: int, name: str = "", goal: str = "", start: str = "", end: str = ""
) -> dict[str, Any]:
    from .jira import JiraClient

    if not (name or goal or start or end):
        raise OpError("nothing_to_update", "Give at least one of name, goal, start or end.")
    return JiraClient().update_sprint(
        sprint_id, name=name or None, goal=goal or None, start=start or None, end=end or None
    ).as_dict()


def jira_assign(issue_keys: list[str], assignee: str) -> dict[str, Any]:
    from .jira import JiraClient

    jira = JiraClient()
    if assignee.strip().lower() in ("", "unassigned", "none"):
        member_name, user = "Unassigned", None
    else:
        member = jira.config.member_by(assignee)
        if member is None:
            known = ", ".join(m.name for m in jira.config.members) or "(roster is empty)"
            raise OpError(
                "unknown_member",
                f"{assignee!r} is not in [[team.members]] in config.toml. Known: {known}. "
                "Add them there (INSTALL.md, team roster) to assign them work.",
            )
        if not member.jira:
            raise OpError(
                "no_jira_id",
                f"{member.name} has no `jira` value in [[team.members]] in config.toml: "
                "the Jira username on Data Center, the accountId on Cloud (INSTALL.md, team roster).",
            )
        member_name, user = member.name, member.jira
    for key in issue_keys:
        jira.assign(key, user)
    return {"assignee": member_name, "issues": issue_keys}


# ------------------------------------------------------------------- gitlab


def gitlab_branch_summary(repo_path: str, target_branch: str = "") -> dict[str, Any]:
    from .gitlab import local_branch_summary

    return local_branch_summary(repo_path, target_branch or load_config().gitlab_target_branch)


def gitlab_compare(source: str, target: str = "", project: str = "") -> dict[str, Any]:
    from .gitlab import GitLabClient

    return GitLabClient().compare(
        source, target or load_config().gitlab_target_branch, project or None
    )


def gitlab_list_mrs(state: str = "opened", author: str = "", limit: int = 30) -> list[dict[str, Any]]:
    from .gitlab import GitLabClient

    return [
        mr.as_dict()
        for mr in GitLabClient().list_merge_requests(state=state, author=author or None, limit=limit)
    ]


def gitlab_create_mr(
    source_branch: str,
    title: str,
    description: str,
    target_branch: str = "",
    project: str = "",
    draft: bool = True,
    labels: list[str] | None = None,
) -> dict[str, Any]:
    from .gitlab import GitLabClient

    return (
        GitLabClient()
        .create_merge_request(
            source_branch=source_branch,
            title=title,
            description=description,
            target_branch=target_branch or None,
            project=project or None,
            draft=draft,
            labels=labels,
        )
        .as_dict()
    )


def gitlab_update_mr(
    iid: int,
    description: str = "",
    title: str = "",
    project: str = "",
    labels: list[str] | None = None,
) -> dict[str, Any]:
    from .gitlab import GitLabClient

    return (
        GitLabClient()
        .update_merge_request(
            iid,
            project=project or None,
            title=title or None,
            description=description or None,
            labels=labels,
        )
        .as_dict()
    )


# -------------------------------------------------------------------- vault


def vault_search(query: str, limit: int = 30) -> list[dict[str, Any]]:
    from .vault import Vault

    return Vault().search(query, limit)


def vault_read(title: str) -> dict[str, Any]:
    from .vault import Vault

    note = Vault().read(title)
    if not note:
        raise OpError("not_found", f"No note titled {title!r}.")
    return {
        "title": note.title,
        "path": str(note.path),
        "frontmatter": note.frontmatter,
        "body": note.body,
    }


def vault_links(title: str) -> dict[str, Any]:
    from .vault import Vault

    vault = Vault()
    return {"note": title, "backlinks": vault.backlinks(title), "outlinks": vault.outlinks(title)}


def vault_stats() -> dict[str, Any]:
    from .vault import Vault

    return Vault().stats()


def vault_write_note(
    title: str,
    kind: str,
    markdown: str,
    tags: list[str] | None = None,
    links_to: list[str] | None = None,
) -> dict[str, Any]:
    from .vault import Vault, slug

    frontmatter: dict[str, Any] = {"type": kind, "tags": tags or [kind]}
    body = markdown
    if links_to:
        frontmatter["related"] = [f"[[{slug(t)}]]" for t in links_to]
        body += "\n\n## Related\n\n" + "\n".join(f"- [[{slug(t)}]]" for t in links_to)

    path = Vault().upsert(title, kind, frontmatter, {"content": body})
    return {"title": title, "path": str(path), "type": kind}


def vault_record_decision(
    title: str,
    context: str,
    decision: str,
    consequences: str = "",
    people: list[str] | None = None,
    related: list[str] | None = None,
) -> dict[str, Any]:
    from .graph import GraphBuilder

    return {
        "title": GraphBuilder().record_decision(
            title, context, decision, consequences, people, related
        )
    }


def vault_sync(sprints_back: int = 3, include_mrs: bool = True) -> dict[str, Any]:
    from .graph import GraphBuilder

    return GraphBuilder().sync_all(sprints_back, include_mrs)


def vault_sync_sprint(sprint_id: int = 0) -> dict[str, Any]:
    from .graph import GraphBuilder
    from .jira import JiraClient

    builder = GraphBuilder()
    jira = JiraClient(builder.config)
    sprint = (
        next((s for s in jira.sprints() if s.id == sprint_id), None)
        if sprint_id
        else jira.active_sprint()
    )
    if not sprint:
        raise OpError("not_found", f"No sprint {sprint_id or '(active)'}.")
    issues = jira.sprint_issues(sprint.id)
    title = builder.sync_sprint(sprint, issues, jira.workload(sprint.id), jira.done_in(sprint))
    return {"note": title, "sprint": sprint.as_dict(), "issues": len(issues)}


def vault_sync_mr(iid: int, project: str = "", summary: str = "") -> dict[str, Any]:
    from .gitlab import GitLabClient
    from .graph import GraphBuilder, extract_issue_key
    from .jira import JiraClient

    builder = GraphBuilder()
    target = project or builder.config.gitlab_default_project
    mr = GitLabClient(builder.config).get_merge_request(iid, target)

    key = extract_issue_key(mr.source_branch, mr.title)
    issue = None
    if key:
        try:
            issue = JiraClient(builder.config).get_issue(key)
        except Exception:  # a branch may name an issue that no longer exists
            issue = None

    title = builder.sync_merge_request(mr, target, issue, summary=summary)
    return {"note": title, "mr": mr.as_dict(), "issue": key or None}


# ----------------------------------------------------------------------- ui


def _ui(fn: Any, *args: Any) -> dict[str, Any]:
    from .ui import UIError

    try:
        return fn(*args)
    except UIError as exc:
        raise OpError("ui", str(exc)) from exc


def ui_style() -> dict[str, Any]:
    from . import ui

    return _ui(ui.style_profile)


def ui_login(url: str) -> dict[str, Any]:
    from . import ui

    return _ui(ui.login, url)


def ui_capture(url: str, name: str, width: int = 0, height: int = 0) -> dict[str, Any]:
    from . import ui

    return _ui(ui.capture, url, name, width, height)


def ui_render_mock(html_path: str, width: int = 0, height: int = 0) -> dict[str, Any]:
    from . import ui

    return _ui(ui.render, html_path, width, height)


# --------------------------------------------------------------------- meta


def doctor() -> dict[str, Any]:
    from .doctor import run_checks

    return run_checks()
