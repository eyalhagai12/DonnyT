"""MCP server exposing the toolkit to Claude Code.

This is the only part of the repo that needs a third-party package (``mcp``).
Everything else is standard library, so if the MCP dependency cannot be
installed on an isolated host, ``python -m donnyt.cli`` still does the whole
job from the command line.

Registered in .mcp.json; Claude Code starts it over stdio.

Every tool here is a thin wrapper over :mod:`donnyt.ops`, which the CLI calls
too -- add new behaviour there, then expose it in both places.
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
            "The CLI does everything without it:  python -m donnyt.cli tools\n"
            "To add it, re-run the installer with -IndexUrl / --index-url <internal mirror>,\n"
            "or ship a vendor/wheels bundle built for this machine. See INSTALL.md step 3."
        ) from exc

from . import ops
from .config import ConfigError

mcp = _Server("donnyt")


def _guard(fn, *args: Any, **kwargs: Any) -> Any:
    """Return errors as data so the model can act on them instead of crashing."""
    try:
        return fn(*args, **kwargs)
    except ops.OpError as exc:
        return {"error": exc.code, "message": str(exc)}
    except ConfigError as exc:
        return {"error": "config", "message": str(exc)}
    except Exception as exc:
        return {"error": type(exc).__name__, "message": str(exc)}


# ---------------------------------------------------------------- confluence


@mcp.tool()
def confluence_get_mr_template(raw: bool = False) -> dict[str, Any]:
    """Fetch the team's merge-request template from Confluence as Markdown.

    Returns the template body plus its section headings. Use this before
    writing any MR description so the description matches the team's agreed
    structure rather than an invented one.

    Set `raw=True` to get the untouched Confluence storage-format XHTML
    instead of Markdown. Use this only to diagnose a template that converted
    wrong: compare the raw XHTML against the Markdown to see which element
    (a macro, a layout, a table) did not carry over, then either work around
    it in the Markdown you write, or fix `src/donnyt/_html2md.py` to handle it
    -- see INTERNAL_SETUP.md.
    """
    return _guard(ops.mr_template, raw)


@mcp.tool()
def confluence_get_page(page_id: str, raw: bool = False) -> dict[str, Any]:
    """Read a Confluence page by id and return its content as Markdown.

    Set `raw=True` to get the untouched storage-format XHTML instead, for
    diagnosing a conversion problem.
    """
    return _guard(ops.confluence_page, page_id, raw)


@mcp.tool()
def confluence_search(cql: str, limit: int = 25) -> Any:
    """Search Confluence with a CQL query.

    Example: `type=page AND space="ENG" AND text ~ "onboarding"`.
    """
    return _guard(ops.confluence_search, cql, limit)


@mcp.tool()
def confluence_publish(title: str, markdown: str, parent_id: str = "") -> Any:
    """Create or update a Confluence page from Markdown.

    Updates the page in place when one of that title already exists in the
    configured space, otherwise creates it under `parent_id`.
    """
    return _guard(ops.confluence_publish, title, markdown, parent_id)


# --------------------------------------------------------------------- jira


@mcp.tool()
def jira_search(jql: str, limit: int = 50) -> Any:
    """Run a JQL query and return matching issues."""
    return _guard(ops.jira_search, jql, limit)


@mcp.tool()
def jira_get_issue(key: str) -> Any:
    """Fetch a single Jira issue by key, e.g. TEAM-1234."""
    return _guard(ops.jira_issue, key)


@mcp.tool()
def jira_sprints(state: str = "") -> Any:
    """List sprints on the configured board.

    `state` filters to one of: active, future, closed. Empty returns all.
    """
    return _guard(ops.jira_sprints, state)


@mcp.tool()
def jira_sprint_issues(sprint_id: int = 0) -> Any:
    """Issues in a sprint, in rank order. Defaults to the active sprint."""
    return _guard(ops.jira_sprint_issues, sprint_id)


@mcp.tool()
def jira_backlog(limit: int = 60) -> Any:
    """Board backlog in rank order -- the candidate pool for the next sprint."""
    return _guard(ops.jira_backlog, limit)


@mcp.tool()
def jira_velocity(sprints_back: int = 5) -> Any:
    """Completed story points per recent closed sprint, plus the average.

    Size the next sprint against `average_completed_points`, not against
    what was committed.
    """
    return _guard(ops.jira_velocity, sprints_back)


@mcp.tool()
def jira_workload(sprint_id: int = 0) -> Any:
    """Points per assignee in a sprint, compared against configured capacity.

    `over_by` is positive where someone is loaded beyond their capacity.
    """
    return _guard(ops.jira_workload, sprint_id)


@mcp.tool()
def jira_create_sprint(name: str, start: str = "", end: str = "", goal: str = "") -> Any:
    """Create a sprint on the configured board. Dates are ISO `YYYY-MM-DD`."""
    return _guard(ops.jira_create_sprint, name, start, end, goal)


@mcp.tool()
def jira_add_to_sprint(sprint_id: int, issue_keys: list[str]) -> Any:
    """Move issues into a sprint. Batched automatically past Jira's 50-issue cap."""
    return _guard(ops.jira_add_to_sprint, sprint_id, issue_keys)


# ------------------------------------------------------------------- gitlab


@mcp.tool()
def gitlab_branch_summary(repo_path: str, target_branch: str = "") -> Any:
    """Commits, changed files and diffstat on a local branch versus its target.

    Reads the working repo on disk, so an MR description can be drafted before
    the branch is pushed. `repo_path` is the path to the git checkout.
    """
    return _guard(ops.gitlab_branch_summary, repo_path, target_branch)


@mcp.tool()
def gitlab_compare(source: str, target: str = "", project: str = "") -> Any:
    """Compare two refs on the GitLab server, returning commits and files."""
    return _guard(ops.gitlab_compare, source, target, project)


@mcp.tool()
def gitlab_list_mrs(state: str = "opened", author: str = "", limit: int = 30) -> Any:
    """List merge requests on the configured project."""
    return _guard(ops.gitlab_list_mrs, state, author, limit)


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
        ops.gitlab_create_mr,
        source_branch, title, description, target_branch, project, draft, labels,
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
    return _guard(ops.gitlab_update_mr, iid, description, title, project, labels)


# -------------------------------------------------------------------- vault


@mcp.tool()
def vault_search(query: str, limit: int = 30) -> Any:
    """Full-text search the Obsidian vault, with one line of context per hit."""
    return _guard(ops.vault_search, query, limit)


@mcp.tool()
def vault_read(title: str) -> Any:
    """Read a vault note by title, returning its frontmatter and body."""
    return _guard(ops.vault_read, title)


@mcp.tool()
def vault_links(title: str) -> Any:
    """Inbound and outbound links for a note -- its edges in the graph.

    Backlinks on a person note are their history: every sprint, MR and
    decision that referenced them.
    """
    return _guard(ops.vault_links, title)


@mcp.tool()
def vault_stats() -> Any:
    """Note counts per type, and where the vault lives on disk."""
    return _guard(ops.vault_stats)


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
    return _guard(ops.vault_write_note, title, kind, markdown, tags, links_to)


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
        ops.vault_record_decision, title, context, decision, consequences, people, related
    )


@mcp.tool()
def vault_sync(sprints_back: int = 3, include_mrs: bool = True) -> Any:
    """Pull recent sprints and open MRs from Jira and GitLab into the vault.

    Creates or refreshes sprint notes, MR notes and the person notes they link
    to. Run this before asking questions about team history.
    """
    return _guard(ops.vault_sync, sprints_back, include_mrs)


@mcp.tool()
def vault_sync_sprint(sprint_id: int = 0) -> Any:
    """Write one sprint's note from Jira. Defaults to the active sprint."""
    return _guard(ops.vault_sync_sprint, sprint_id)


@mcp.tool()
def vault_sync_mr(iid: int, project: str = "", summary: str = "") -> Any:
    """Write a merge request's note, linking it to its Jira issue and author.

    The Jira key is read from the branch name or MR title, e.g. `TEAM-1234`.
    """
    return _guard(ops.vault_sync_mr, iid, project, summary)


# --------------------------------------------------------------------- meta


@mcp.tool()
def donnyt_doctor() -> Any:
    """Check configuration and connectivity to Confluence, Jira and GitLab.

    Run this first when anything misbehaves -- it reports exactly which
    credential or setting is missing.
    """
    return _guard(ops.doctor)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
