# DonnyT — working notes for Claude

A team-lead toolkit: Confluence-templated GitLab MRs, Jira sprint planning, and
an Obsidian knowledge graph. Read `README.md` for the shape of it and
`INSTALL.md` for setup.

## Hard constraints

**This repo must install and run on an airtight internal network.** That is not
aspirational — it is the deployment target.

- **Do not add third-party dependencies to the core.** `src/donnyt/` is
  stdlib-only: `urllib` for HTTP, `tomllib` for config, `html.parser` for HTML.
  Adding `requests`, `httpx`, `pyyaml` or similar breaks the offline install and
  means re-bundling wheels for every target platform. If something seems to need
  a library, write the small piece you actually need instead.
- `mcp` is the sole exception, and only `mcp_server.py` may import it. Every
  feature must remain reachable from `cli.py` without it.
- **No network calls at import time**, and no assumption that PyPI, GitHub or
  any public host is reachable.
- Assume TLS interception and proxies. All HTTP goes through
  `_http.JSONClient`, which handles both. Don't bypass it.

## Layout

| File | Responsibility |
| --- | --- |
| `_http.py` | HTTP + auth + TLS/proxy handling. All network traffic goes here. |
| `_html2md.py` | Confluence storage format ↔ Markdown. |
| `config.py` | `.env` + `config.toml`. `repo_root()` handles the installed-vs-source split. Cloud vs Data Center, URLs and auth headers are resolved here. |
| `confluence.py` `jira.py` `gitlab.py` | Thin REST clients returning dataclasses. Branch on `self.cloud` where Cloud and Data Center APIs differ. |
| `vault.py` | Obsidian notes: frontmatter, links, managed blocks. |
| `ui.py` | Mockups: screenshots of the running app and HTML → PNG, via the installed Edge/Chrome run headless. |
| `graph.py` | Domain layer — turns API facts into linked notes. |
| `ops.py` | Every operation, once. Both front ends call it; expected failures raise `OpError(code, msg)`. |
| `mcp_server.py` | Tool definitions over `ops`. One-line bodies; logic belongs in `ops` or below. |
| `cli.py` | The same operations from a terminal. `TOOLS` maps each MCP tool to its command. |
| `doctor.py` | Preflight checks. |

## Conventions

- **Every MCP tool needs a CLI equivalent.** The CLI is the whole toolkit when
  `mcp` cannot be installed, and the installer falls back to that CLI-only mode
  on its own. A new tool means: the function in `ops.py`, the tool in
  `mcp_server.py`, the subcommand and handler in `cli.py`, and its line in
  `cli.TOOLS`.
- **Support both Atlassian flavours.** Anything new against Jira or Confluence
  must work on Cloud (`/rest/api/3`, Confluence `/api/v2`) and Data Center
  (`/rest/api/2`, Confluence `/rest/api/content`). Use `self.api` / `self.cloud`
  in the clients; never hardcode a host or version.
- **Tool docstrings are the model's only documentation.** Say what the tool
  returns and when to reach for it, not just what it does.
- **Errors are returned as data**, via `_guard` in `mcp_server.py`, so the model
  can act on them. Error messages name the exact setting or credential at fault
  and point at the INSTALL.md step.
- **Never overwrite the user's prose in the vault.** Generated content goes
  inside `<!-- donnyt:begin <id> -->` / `<!-- donnyt:end <id> -->` markers via
  `Vault.upsert`. Everything outside them is theirs.
- Type hints throughout; dataclasses for API results, not raw dicts.

## Behaviour when using the tools

- **Confirm before anything the team sees.** Creating an MR, creating a sprint,
  moving issues, publishing to Confluence — show the content, then ask.
- **Size sprints on `completed` points, never `committed`.** The distinction is
  the entire point of `jira_velocity`.
- **Person notes are private.** Never publish 1:1 or person-note content to
  Confluence or GitLab. Report what the record shows; don't editorialise about
  someone's performance.
- **Don't invent identifiers.** Issue keys, MR numbers, account ids and page ids
  either come from a tool call or get asked about.
- **Fetch the Confluence template; never reconstruct it from memory.** If it
  can't be fetched, stop and say so.

## Testing

No test suite yet. The stdlib pieces — `_html2md`, `vault` frontmatter and
managed blocks — are pure functions and are the right place to start if you add
one. Check changes against a live instance with:

```bash
python -m donnyt.cli doctor
```

## Gotchas

- `repo_root()` must not be derived from `__file__` alone; an installed copy
  lives in `site-packages`. It checks `DONNYT_HOME`, then the working directory,
  then the module path, keying off `config.example.toml`.
- Jira sprints exist only in `/rest/agile/1.0`, not `/rest/api/3`. It is the
  same on Cloud and Data Center.
- The board sprint list pages at 50 in id order; `JiraClient.sprints` pages
  through all of them, or velocity silently reads the oldest sprints.
- Cloud JQL search uses `/search/jql` with page tokens; Data Center only has
  `/search` with `startAt`. `JiraClient.search` does both.
- Data Center Confluence often lives under a context path (`/confluence`), and
  its `_links.webui` is relative to that — build URLs from `config.confluence_url`.
- `jira_add_to_sprint` batches at 50 — Jira's hard cap per call.
- The `mcp` SDK renamed `FastMCP` to `MCPServer` in 2.0. `mcp_server.py`
  imports either.
- `ui.py` drives the browser's own command line (`--headless=new --screenshot`),
  not an automation library: screenshots are one viewport, not the full page.
  Renders block all network access, so a mock that needs a CDN or web font
  fails here exactly as it would on the isolated host.
- `ui_login` and `ui_capture` share `.donnyt/browser-profile`; Chromium locks a
  profile to one process, so capture fails while the login window is open.
- `confluence_publish` never attaches files to the page itself: they go on a
  child page `<title> - Attachments` (titles are unique per space), and
  `markdown_to_storage(..., attachment_page=)` points each
  `![](attachment:x.png)` there with a nested `<ri:page>`.
- Confluence attachments use the v1 API on both flavours (Cloud v2 cannot
  upload). `attach` looks the name up and posts to `/{id}/data` to replace;
  Data Center has no create-or-update `PUT`.
- Confluence has no Markdown body format. `markdown_to_storage` covers the
  subset this toolkit emits; extend it rather than shipping raw HTML.
