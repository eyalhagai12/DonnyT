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
| `config.py` | `.env` + `config.toml`. `repo_root()` handles the installed-vs-source split. |
| `confluence.py` `jira.py` `gitlab.py` | Thin REST clients returning dataclasses. |
| `vault.py` | Obsidian notes: frontmatter, links, managed blocks. |
| `graph.py` | Domain layer — turns API facts into linked notes. |
| `mcp_server.py` | Tool definitions. Thin wrappers; logic belongs below. |
| `cli.py` | Terminal equivalent of every tool. |
| `doctor.py` | Preflight checks. |

## Conventions

- **Every MCP tool needs a CLI equivalent.** The CLI is the fallback when `mcp`
  cannot be installed.
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
- Jira sprints exist only in `/rest/agile/1.0`, not `/rest/api/3`.
- `jira_add_to_sprint` batches at 50 — Jira's hard cap per call.
- The `mcp` SDK renamed `FastMCP` to `MCPServer` in 2.0. `mcp_server.py`
  imports either.
- Confluence has no Markdown body format. `markdown_to_storage` covers the
  subset this toolkit emits; extend it rather than shipping raw HTML.
