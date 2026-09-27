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
def confluence_get_prd_template(raw: bool = False) -> dict[str, Any]:
    """Fetch the team's product requirements document (PRD) template from Confluence as Markdown.

    Returns the template body, its section headings, and `parent_id`: the page
    a finished PRD should be published under (pass it to `confluence_publish`;
    empty means the space root). Use this before drafting any PRD so it
    follows the team's agreed structure rather than an invented one.

    Fails with `no_prd_template` when the template page is not configured --
    stop and report that rather than inventing a structure.

    Set `raw=True` for the untouched storage-format XHTML, to diagnose a
    section that converted wrong.
    """
    return _guard(ops.prd_template, raw)


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
def confluence_publish(
    title: str, markdown: str, parent_id: str = "", attachments: list[str] | None = None
) -> Any:
    """Create or update a Confluence page from Markdown. Team-visible: confirm first.

    Updates the page in place when one of that title already exists in the
    configured space, otherwise creates it under `parent_id`.

    `attachments` are local file paths. They are uploaded to a child page,
    "<title> - Attachments", created on first use, so the page itself holds
    only the document; an upload replaces a file of the same name. Embed an
    image in the Markdown as `![Alt text](attachment:file-name.png)` -- it is
    pointed at the attachments page automatically. Returns the page, whether
    it was created or updated, the attachments page and each upload.
    """
    return _guard(ops.confluence_publish, title, markdown, parent_id, attachments)


# --------------------------------------------------------------------- jira


@mcp.tool()
def jira_search(jql: str, limit: int = 50) -> Any:
    """Run a JQL query and return matching issues.

    Each issue's `parent` is its epic (or parent issue) key on both Cloud and
    Data Center. To list an epic's children, query `parent = TEAM-1` on Cloud
    and `"Epic Link" = TEAM-1` on Data Center.
    """
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
    """Board backlog in rank order -- the candidate pool for the next sprint.

    Each issue's `parent` is the epic it belongs to, so a sprint can be built
    around one epic by filtering on it.
    """
    return _guard(ops.jira_backlog, limit)


@mcp.tool()
def jira_velocity(sprints_back: int = 5) -> Any:
    """Completed work per recent closed sprint -- issues and story points -- plus the averages.

    `average_completed_issues` is always there. `average_completed_points`
    covers only sprints where most issues were estimated (`estimated` per
    sprint, `estimated_sprints` in total) and is null when none were: a team
    that doesn't estimate has no points velocity, not a velocity of 0. Size
    against completed work, never against what was committed.
    """
    return _guard(ops.jira_velocity, sprints_back)


@mcp.tool()
def jira_workload(sprint_id: int = 0) -> Any:
    """Issues and points per assignee in a sprint, compared against configured capacity.

    Each person has `issues`, `unestimated` (issues with no points) and
    `points`; `over_by` is positive where someone's points exceed their
    capacity. With unestimated work, compare issue counts, not points.
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


@mcp.tool()
def jira_update_sprint(sprint_id: int, name: str = "", goal: str = "", start: str = "", end: str = "") -> Any:
    """Change an existing sprint's name, goal or dates (ISO `YYYY-MM-DD`). Team-visible: confirm first.

    Empty arguments are left as they are. Use it to give a planned sprint its
    goal when the sprint already exists; `jira_create_sprint` only sets one on
    creation. Returns the updated sprint.
    """
    return _guard(ops.jira_update_sprint, sprint_id, name, goal, start, end)


@mcp.tool()
def jira_assign(issue_keys: list[str], assignee: str) -> Any:
    """Assign issues to one team member. Team-visible: confirm first.

    `assignee` is a name, Jira id or GitLab username from the team roster in
    config.toml; "unassigned" clears the assignee. Fails with `unknown_member`
    for anyone not in the roster, so only planned team members get work.
    Returns the member's name and the issues assigned.
    """
    return _guard(ops.jira_assign, issue_keys, assignee)


# ------------------------------------------------------------------- gitlab


@mcp.tool()
def gitlab_list_mrs(state: str = "opened", author: str = "", limit: int = 30) -> Any:
    """List merge requests on the configured project -- read-only history.

    `state` is opened, merged, closed or all. Who did what in a sprint is
    already in its note's "Done by" section (`vault_sync_sprint`); reach for
    this for anything else about past merged work.
    """
    return _guard(ops.gitlab_list_mrs, state, author, limit)


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

    Backlinks on a person note are their history: every sprint and decision
    that referenced them.
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
    regeneration. `kind` is one of: person, sprint, project, decision,
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
def vault_sync(sprints_back: int = 3) -> Any:
    """Pull the active sprint and recent closed ones from Jira and GitLab into the vault.

    Creates or refreshes each sprint note -- overview, workload, issues and
    "Done by" (what each person finished, merged and reviewed) -- and the
    person notes they link to. Run this before asking about team history.
    """
    return _guard(ops.vault_sync, sprints_back)


@mcp.tool()
def vault_sprint_brief(title: str) -> Any:
    """Read the lead's sprint brief, `Sprints/<title>.md`: the input to sprint planning. Call it first.

    Returns `start`/`end` and `working_days` (from the configured weekend);
    `vectors`, the sprint's goals, in priority order; `availability` and
    `on_call` (table rows, or the section's text if it is not a table);
    `must_include` / `keep_out` issue keys; `notes` and `other_sections`
    (any heading the template doesn't have, as text); `people`, with each
    roster member's and each named person's `role` and `focus` from their
    person note, whether they can be assigned (`in_roster`, `jira_set`);
    `jira_sprint`, the open Jira sprint that already has this name (update it
    rather than create a second); and `missing`, the facts to ask the user
    for before planning.

    `focus` is private: use it to decide assignments, never quote it in
    Jira, Confluence or GitLab.
    """
    return _guard(ops.vault_sprint_brief, title)


@mcp.tool()
def vault_sync_sprint(sprint_id: int = 0, plan: str = "") -> Any:
    """Write one sprint's note from Jira. Defaults to the active sprint.

    The note is `Sprints/<sprint name>.md`; if a sprint brief of that name
    exists, the Jira facts go below it and the brief is kept. Pass `plan`
    (Markdown) after planning to record the reasoning: what was picked for
    which vector, what was cut and why, how it was sized, focus conflicts.
    A later sync without `plan` keeps the last one.
    """
    return _guard(ops.vault_sync_sprint, sprint_id, plan)


# ----------------------------------------------------------------------- ui


@mcp.tool()
def ui_style() -> Any:
    """What the toolkit knows about how the team's system looks. Call it first when making UI mockups.

    Returns `screenshots` (paths and pixel sizes of reference screenshots),
    `notes` (the hand-written style.md: colours, fonts, conventions), the
    `browser` used for rendering (null means mockups cannot be rendered) and
    `mocks_dir`, where mockup HTML should be written. Read every screenshot
    path with the Read tool to actually see the style; the paths alone say
    nothing about it.
    """
    return _guard(ops.ui_style)


@mcp.tool()
def ui_login(url: str) -> Any:
    """Open a visible browser window on the internal app so the user can sign in once.

    Uses DonnyT's own browser profile, so `ui_capture` can then take
    screenshots while logged in. Tell the user to sign in and then CLOSE the
    window: the profile is locked while it is open. Only needed when the app
    requires a login; try `ui_capture` first.
    """
    return _guard(ops.ui_login, url)


@mcp.tool()
def ui_capture(url: str, name: str, width: int = 0, height: int = 0) -> Any:
    """Screenshot a page of the running system into the style folder as a reference.

    Saves `screens/<name>.png` in the style folder and returns its path and
    size; Read it to check it shows the page and not a login form (if it does,
    use `ui_login` first). Captures one viewport (default size from config),
    not the full scrolling page.
    """
    return _guard(ops.ui_capture, url, name, width, height)


@mcp.tool()
def ui_render_mock(html_path: str, width: int = 0, height: int = 0) -> Any:
    """Render a self-contained HTML mockup to a PNG next to it, and return the PNG path.

    Read the PNG to check the result against the reference screenshots and
    fix the HTML until it matches. The render has no network access: inline
    all CSS, use system fonts, and reference no external URL. Increase
    `height` for screens taller than the default viewport.
    """
    return _guard(ops.ui_render_mock, html_path, width, height)


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
