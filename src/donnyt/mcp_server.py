"""MCP server exposing the toolkit to Claude Code.

This is the only part of the repo that needs a third-party package (``mcp``).
Everything else is standard library, so if the MCP dependency cannot be
installed on an isolated host, ``python -m donnyt.cli`` still does the whole
job from the command line.

Registered in .mcp.json; Claude Code starts it over stdio.
"""

from __future__ import annotations

from typing import Any

# The SDK renamed FastMCP to MCPServer in 2.0. The decorator and run() APIs are
# identical, so support both rather than pinning the isolated host to one major.
try:
    from mcp.server.mcpserver import MCPServer as _Server  # mcp >= 2.0
except ImportError:
    try:
        from mcp.server.fastmcp import FastMCP as _Server  # mcp 1.x
    except ImportError as exc:  # pragma: no cover - environment guard
        raise SystemExit(
            "The 'mcp' package is not installed, or its API is not recognised.\n"
            "Offline install:  pip install --no-index --find-links vendor/wheels mcp\n"
            "Online install:   pip install mcp\n"
            "See INSTALL.md step 3."
        ) from exc

from .confluence import ConfluenceClient
from .config import ConfigError, load_config
from .gitlab import GitLabClient, local_branch_summary
from .graph import GraphBuilder, extract_issue_key, fetch_mr_template
from .jira import JiraClient
from .vault import Vault

mcp = _Server("donnyt")


def _guard(fn, *args: Any, **kwargs: Any) -> Any:
    """Return errors as data so the model can act on them instead of crashing."""
    try:
        return fn(*args, **kwargs)
    except ConfigError as exc:
        return {"error": "config", "message": str(exc)}
    except Exception as exc:
        return {"error": type(exc).__name__, "message": str(exc)}


# ---------------------------------------------------------------- confluence


@mcp.tool()
def confluence_get_mr_template() -> dict[str, Any]:
    """Fetch the team's merge-request template from Confluence as Markdown.

    Returns the template body plus its section headings. Use this before
    writing any MR description so the description matches the team's agreed
    structure rather than an invented one.
    """
    return _guard(fetch_mr_template)


@mcp.tool()
def confluence_get_page(page_id: str) -> dict[str, Any]:
    """Read a Confluence page by id and return its content as Markdown."""

    def run() -> dict[str, Any]:
        page = ConfluenceClient().get_page(page_id)
        return {**page.summary(), "markdown": page.markdown}

    return _guard(run)


@mcp.tool()
def confluence_search(cql: str, limit: int = 25) -> Any:
    """Search Confluence with a CQL query.

    Example: `type=page AND space="ENG" AND text ~ "onboarding"`.
    """
    return _guard(lambda: ConfluenceClient().search(cql, limit))


@mcp.tool()
def confluence_publish(title: str, markdown: str, parent_id: str = "") -> Any:
    """Create or update a Confluence page from Markdown.

    Updates the page in place when one of that title already exists in the
    configured space, otherwise creates it under `parent_id`.
    """

    def run() -> dict[str, Any]:
        client = ConfluenceClient()
        existing = client.find_page(title)
        parent = parent_id or client.config.sprint_plan_parent_page_id or None
        page = (
            client.update_page(existing.id, title, markdown)
            if existing
            else client.create_page(title, markdown, parent_id=parent)
        )
        return {**page.summary(), "action": "updated" if existing else "created"}

    return _guard(run)


# --------------------------------------------------------------------- jira


@mcp.tool()
def jira_search(jql: str, limit: int = 50) -> Any:
    """Run a JQL query and return matching issues."""
    return _guard(lambda: [i.as_dict() for i in JiraClient().search(jql, limit)])


@mcp.tool()
def jira_get_issue(key: str) -> Any:
    """Fetch a single Jira issue by key, e.g. TEAM-1234."""
    return _guard(lambda: JiraClient().get_issue(key).as_dict())


@mcp.tool()
def jira_sprints(state: str = "") -> Any:
    """List sprints on the configured board.

    `state` filters to one of: active, future, closed. Empty returns all.
    """
    return _guard(lambda: [s.as_dict() for s in JiraClient().sprints(state=state or None)])


@mcp.tool()
def jira_sprint_issues(sprint_id: int = 0) -> Any:
    """Issues in a sprint, in rank order. Defaults to the active sprint."""

    def run() -> Any:
        jira = JiraClient()
        target = sprint_id
        if not target:
            active = jira.active_sprint()
            if not active:
                return {"error": "no_active_sprint", "message": "No active sprint on this board."}
            target = active.id
        return {"sprint_id": target, "issues": [i.as_dict() for i in jira.sprint_issues(target)]}

    return _guard(run)


@mcp.tool()
def jira_backlog(limit: int = 60) -> Any:
    """Board backlog in rank order -- the candidate pool for the next sprint."""
    return _guard(lambda: [i.as_dict() for i in JiraClient().backlog(limit=limit)])


@mcp.tool()
def jira_velocity(sprints_back: int = 5) -> Any:
    """Completed story points per recent closed sprint, plus the average.

    Size the next sprint against `average_completed_points`, not against
    what was committed.
    """
    return _guard(lambda: JiraClient().velocity(sprints_back=sprints_back))


@mcp.tool()
def jira_workload(sprint_id: int = 0) -> Any:
    """Points per assignee in a sprint, compared against configured capacity.

    `over_by` is positive where someone is loaded beyond their capacity.
    """

    def run() -> Any:
        jira = JiraClient()
        target = sprint_id
        if not target:
            active = jira.active_sprint()
            if not active:
                return {"error": "no_active_sprint", "message": "No active sprint on this board."}
            target = active.id
        return jira.workload(target)

    return _guard(run)


@mcp.tool()
def jira_create_sprint(name: str, start: str = "", end: str = "", goal: str = "") -> Any:
    """Create a sprint on the configured board. Dates are ISO `YYYY-MM-DD`."""
    return _guard(
        lambda: JiraClient()
        .create_sprint(name, start=start or None, end=end or None, goal=goal)
        .as_dict()
    )


@mcp.tool()
def jira_add_to_sprint(sprint_id: int, issue_keys: list[str]) -> Any:
    """Move issues into a sprint. Batched automatically past Jira's 50-issue cap."""
    return _guard(lambda: JiraClient().move_issues_to_sprint(sprint_id, issue_keys))


# ------------------------------------------------------------------- gitlab


@mcp.tool()
def gitlab_branch_summary(repo_path: str, target_branch: str = "") -> Any:
    """Commits, changed files and diffstat on a local branch versus its target.

    Reads the working repo on disk, so an MR description can be drafted before
    the branch is pushed. `repo_path` is the path to the git checkout.
    """
    return _guard(
        lambda: local_branch_summary(
            repo_path, target_branch or load_config().gitlab_target_branch
        )
    )


@mcp.tool()
def gitlab_compare(source: str, target: str = "", project: str = "") -> Any:
    """Compare two refs on the GitLab server, returning commits and files."""
    return _guard(
        lambda: GitLabClient().compare(
            source, target or load_config().gitlab_target_branch, project or None
        )
    )


@mcp.tool()
def gitlab_list_mrs(state: str = "opened", author: str = "", limit: int = 30) -> Any:
    """List merge requests on the configured project."""
    return _guard(
        lambda: [
            mr.as_dict()
            for mr in GitLabClient().list_merge_requests(
                state=state, author=author or None, limit=limit
            )
        ]
    )


@mcp.tool()
def gitlab_create_mr(
    source_branch: str,
    title: str,
    description: str,
    target_branch: str = "",
    project: str = "",
    draft: bool = True,
    labels: list[str] | None = None,
) -> Any:
    """Open a merge request.

    Creates it as a draft by default. `description` should be the rendered
    Confluence template -- fetch it with `confluence_get_mr_template` first.
    """
    return _guard(
        lambda: GitLabClient()
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


@mcp.tool()
def gitlab_update_mr(
    iid: int,
    description: str = "",
    title: str = "",
    project: str = "",
    labels: list[str] | None = None,
) -> Any:
    """Update an existing merge request's title, description, or labels."""
    return _guard(
        lambda: GitLabClient()
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


@mcp.tool()
def vault_search(query: str, limit: int = 30) -> Any:
    """Full-text search the Obsidian vault, with one line of context per hit."""
    return _guard(lambda: Vault().search(query, limit))


@mcp.tool()
def vault_read(title: str) -> Any:
    """Read a vault note by title, returning its frontmatter and body."""

    def run() -> Any:
        note = Vault().read(title)
        if not note:
            return {"error": "not_found", "message": f"No note titled {title!r}."}
        return {
            "title": note.title,
            "path": str(note.path),
            "frontmatter": note.frontmatter,
            "body": note.body,
        }

    return _guard(run)


@mcp.tool()
def vault_links(title: str) -> Any:
    """Inbound and outbound links for a note -- its edges in the graph.

    Backlinks on a person note are their history: every sprint, MR and
    decision that referenced them.
    """

    def run() -> Any:
        vault = Vault()
        return {
            "note": title,
            "backlinks": vault.backlinks(title),
            "outlinks": vault.outlinks(title),
        }

    return _guard(run)


@mcp.tool()
def vault_stats() -> Any:
    """Note counts per type, and where the vault lives on disk."""
    return _guard(lambda: Vault().stats())


@mcp.tool()
def vault_write_note(
    title: str,
    kind: str,
    markdown: str,
    tags: list[str] | None = None,
    links_to: list[str] | None = None,
) -> Any:
    """Write or refresh a note, preserving anything hand-written.

    Content goes inside a managed block, so prose you typed outside it survives
    regeneration. `kind` is one of: person, sprint, mr, project, decision,
    meeting, topic. `links_to` are note titles to link, forming graph edges.
    """

    def run() -> Any:
        from .vault import slug as _slug

        frontmatter: dict[str, Any] = {"type": kind, "tags": tags or [kind]}
        if links_to:
            frontmatter["related"] = [f"[[{_slug(t)}]]" for t in links_to]

        body = markdown
        if links_to:
            body += "\n\n## Related\n\n" + "\n".join(f"- [[{_slug(t)}]]" for t in links_to)

        path = Vault().upsert(title, kind, frontmatter, {"content": body})
        return {"title": title, "path": str(path), "type": kind}

    return _guard(run)


@mcp.tool()
def vault_record_decision(
    title: str,
    context: str,
    decision: str,
    consequences: str = "",
    people: list[str] | None = None,
    related: list[str] | None = None,
) -> Any:
    """Record a team decision as an ADR-shaped note linked to the people involved."""
    return _guard(
        lambda: {
            "title": GraphBuilder().record_decision(
                title, context, decision, consequences, people, related
            )
        }
    )


@mcp.tool()
def vault_sync(sprints_back: int = 3, include_mrs: bool = True) -> Any:
    """Pull recent sprints and open MRs from Jira and GitLab into the vault.

    Creates or refreshes sprint notes, MR notes and the person notes they link
    to. Run this before asking questions about team history.
    """
    return _guard(lambda: GraphBuilder().sync_all(sprints_back, include_mrs))


@mcp.tool()
def vault_sync_sprint(sprint_id: int = 0) -> Any:
    """Write one sprint's note from Jira. Defaults to the active sprint."""

    def run() -> Any:
        builder = GraphBuilder()
        jira = JiraClient(builder.config)
        sprint = next(
            (s for s in jira.sprints() if s.id == sprint_id), None
        ) if sprint_id else jira.active_sprint()
        if not sprint:
            return {"error": "not_found", "message": f"No sprint {sprint_id or '(active)'}."}
        issues = jira.sprint_issues(sprint.id)
        title = builder.sync_sprint(sprint, issues, jira.workload(sprint.id))
        return {"note": title, "sprint": sprint.as_dict(), "issues": len(issues)}

    return _guard(run)


@mcp.tool()
def vault_sync_mr(iid: int, project: str = "", summary: str = "") -> Any:
    """Write a merge request's note, linking it to its Jira issue and author.

    The Jira key is read from the branch name or MR title, e.g. `TEAM-1234`.
    """

    def run() -> Any:
        builder = GraphBuilder()
        gitlab = GitLabClient(builder.config)
        target = project or builder.config.gitlab_default_project
        mr = gitlab.get_merge_request(iid, target)

        key = extract_issue_key(mr.source_branch, mr.title)
        issue = None
        if key:
            try:
                issue = JiraClient(builder.config).get_issue(key)
            except Exception:
                issue = None

        title = builder.sync_merge_request(mr, target, issue, summary=summary)
        return {"note": title, "mr": mr.as_dict(), "issue": key or None}

    return _guard(run)


# --------------------------------------------------------------------- meta


@mcp.tool()
def donnyt_doctor() -> Any:
    """Check configuration and connectivity to Confluence, Jira and GitLab.

    Run this first when anything misbehaves -- it reports exactly which
    credential or setting is missing.
    """
    from .doctor import run_checks

    return run_checks()


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
