# DonnyT

A team-lead toolkit for Claude Code. Three jobs:

1. **Write merge requests** that follow the team's Confluence template, instead
   of a shape reinvented every time.
2. **Plan sprints** against what the team has actually finished, not what it
   hoped to.
3. **Remember all of it** in an Obsidian knowledge graph, so last quarter stays
   answerable.

Built to run on an **airtight internal network** — no package index, no public
internet. See **[INSTALL.md](INSTALL.md)**.

---

## Install

```powershell
.\install.ps1      # Windows
```
```bash
./install.sh       # macOS / Linux
```

Then fill in `.env` and `config.toml`, and run:

```
python -m donnyt.cli doctor
```

Full walkthrough, credentials and troubleshooting: **[INSTALL.md](INSTALL.md)**.

Setting this up *on* the isolated network, with a weaker model doing the work
and your Confluence template never leaving that network:
**[INTERNAL_SETUP.md](INTERNAL_SETUP.md)**.

---

## Using it

Three skills, invoked in Claude Code:

| Skill | What it does |
| --- | --- |
| `/mr-write` | Fetches the Confluence MR template, reads the actual diff, fills every section, opens the MR as a draft, records it in the vault. |
| `/sprint-plan` | Velocity, capacity, spillover, backlog selection, per-person load. Presents the plan for review before touching Jira. |
| `/vault-sync` | Keeps the graph current; answers questions about team history; preps 1:1s. |

They also trigger on plain language — "write the MR for this branch", "what
should go in the next sprint", "what has Maya been working on".

Everything also works from the terminal:

```bash
python -m donnyt.cli template          # the MR template, as Markdown
python -m donnyt.cli velocity          # completed points per recent sprint
python -m donnyt.cli workload          # per-person load this sprint
python -m donnyt.cli backlog           # ranked candidates for next sprint
python -m donnyt.cli sync              # refresh the vault from Jira + GitLab
python -m donnyt.cli vault-links "Maya Cohen"
```

---

## How it is put together

```
src/donnyt/
  _http.py        stdlib HTTP: basic auth, corporate CA bundles, proxies
  _html2md.py     Confluence storage format <-> Markdown
  config.py       .env + config.toml
  confluence.py   pages, CQL search, the MR template
  jira.py         issues, boards, sprints, velocity, workload
  gitlab.py       merge requests, branch and ref comparison
  vault.py        Obsidian notes, frontmatter, links, managed blocks
  graph.py        turns Jira/GitLab facts into linked notes
  mcp_server.py   28 MCP tools
  cli.py          the same, from a terminal
  doctor.py       preflight checks

.claude/skills/   mr-write, sprint-plan, vault-sync
vault/            the knowledge graph (plain Markdown)
vendor/wheels/    offline install bundle
```

**The core has no third-party dependencies.** HTTP is `urllib`, config is
`tomllib`, HTML is `html.parser`. Only the MCP server needs a package (`mcp`),
so if that cannot be installed on a locked-down host, the CLI still does the
whole job.

`donnyt` is deliberately **not** pip-installed: the installer links `src/` into
the virtual environment, so edits take effect immediately and the offline
install needs no build backend.

---

## The knowledge graph

| Folder | Type | Holds |
| --- | --- | --- |
| `People/` | `person` | One per team member. 1:1s, growth, context. |
| `Sprints/` | `sprint` | Goal, workload, issues. |
| `MRs/` | `mr` | Merge requests worth remembering. |
| `Projects/` | `epic` | Arcs spanning sprints. |
| `Decisions/` | `decision` | Context, decision, consequences. |
| `Meetings/` | `meeting` | Retros, planning, skip-levels. |
| `Topics/` | `topic` | Everything else. |

Edges are `[[wikilinks]]`. **A person's history is their backlinks** — every
sprint, MR and decision that named them shows up on their page automatically,
with nothing appended to it.

### Your writing is safe

Generated content is fenced:

```
<!-- donnyt:begin overview -->
...replaced on every sync...
<!-- donnyt:end overview -->
```

Prose outside those markers is never touched. That is what makes it safe to
keep 1:1 notes on a page that resyncs from Jira every week. Don't type inside a
marked block — write above or below it.

---

## Safety

- **Nothing is published without asking.** Opening an MR, creating a sprint and
  publishing to Confluence are all visible to the team; the skills confirm
  first.
- **Sprints are sized on completed points, never committed points.**
- **1:1 and person notes stay local.** They are never published to Confluence or
  GitLab.
- **Secrets stay out of git.** `.env`, `config.toml` and `.mcp.json` are all
  ignored. When zipping the repo to carry it across, exclude `.env` explicitly —
  see [INSTALL.md](INSTALL.md#a4-zip-it).
