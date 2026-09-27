# DonnyT

A team-lead toolkit for Claude Code. Three jobs:

1. **Plan sprints** from a brief you write in the vault — goals, dates, who is
   away, who is on call — sized against what the team has actually finished,
   with or without story points.
2. **Record who did what.** Each sprint note lists, per person, the tickets
   they finished and the merge requests they merged and reviewed — read from
   Jira and GitLab, worth showing the team.
3. **Remember all of it** in an Obsidian knowledge graph, so last quarter stays
   answerable.

GitLab is read-only, across as many repos as the team works in: each repo is
mapped to the Jira components or labels whose tickets touch it. That history
credits who did what, and is the evidence estimates rest on.

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
and your Confluence templates never leaving that network:
**[INTERNAL_SETUP.md](INTERNAL_SETUP.md)**.

---

## Using it

Five skills, invoked in Claude Code:

| Skill | What it does |
| --- | --- |
| `/prd-write` | Turns a problem statement and a proposed solution into a PRD from the Confluence template: user flows, screens, edge cases and ticket-sized requirements. Asks about gaps instead of inventing them, publishes a draft. Runs before tickets exist; it never creates them. |
| `/ui-mock` | Mockups in the style of your own system: learns the look from screenshots or by capturing the running app, draws each screen as HTML, renders it to PNG with the installed Edge/Chrome. `/prd-write` uses it for the Mockups section. |
| `/sprint-plan` | Reads your sprint brief (`vault/Sprints/<name>.md`), then selects by goal, sizes by availability, assigns by each person's Focus. Works with unestimated issues. Presents the plan for review, then creates the sprint in Jira. || `/estimate` | Sizes issues (XS–XL, as story points) from what similar past work really changed, across every repo the ticket's Jira components map to. Proposes; writes to Jira only after you approve. |
| `/vault-sync` | Keeps the graph current; answers questions about team history; preps 1:1s. |

They also trigger on plain language — "plan the sprint from the brief", "what
should go in the next sprint", "what has Maya been working on".

Everything also works from the terminal:

```bash
python -m donnyt.cli sprint-brief "Sprint 7"   # read a sprint brief
python -m donnyt.cli velocity          # completed issues and points per recent sprint
python -m donnyt.cli workload          # per-person load this sprint
python -m donnyt.cli backlog           # ranked candidates for next sprint
python -m donnyt.cli sync-sprint       # the sprint note, with who did what
python -m donnyt.cli vault-links "Maya Cohen"
```

---

## How it is put together

```
src/donnyt/
  _http.py        stdlib HTTP: basic auth, corporate CA bundles, proxies
  _html2md.py     Confluence storage format <-> Markdown
  config.py       .env + config.toml
  confluence.py   pages, CQL search, the PRD template (Cloud + Data Center)
  jira.py         issues, boards, sprints, velocity, workload (Cloud + Data Center)
  gitlab.py       read-only, per repo: merged work, reviewers, what a ticket changed
  estimate.py     evidence for estimates: similar past work, per repo
  vault.py        Obsidian notes, frontmatter, links, managed blocks
  graph.py        turns Jira/GitLab facts into linked notes
  ops.py          every operation, once -- both front ends call it
  ui.py           mockups: capture the running app, render HTML to PNG
  mcp_server.py   MCP tools over ops.py
  cli.py          the same tools, from a terminal (`donnyt tools` maps them)
  doctor.py       preflight checks

.claude/skills/   sprint-plan, estimate, vault-sync, prd-write, ui-mock
vault/            the knowledge graph (plain Markdown)
vendor/wheels/    offline install bundle
```

**The core has no third-party dependencies.** HTTP is `urllib`, config is
`tomllib`, HTML is `html.parser`. Only the MCP server needs a package (`mcp`),
and it is optional: if the installer finds it in neither the bundled wheels nor
an internal mirror, it installs in CLI-only mode, where every tool is a
`python -m donnyt.cli` command and the skills use those instead.

Works against Atlassian **Cloud or self-hosted Data Center**, with email +
token or personal-access-token auth; `atlassian.deployment` picks the API, and
defaults to working it out from the address.

`donnyt` is deliberately **not** pip-installed: the installer links `src/` into
the virtual environment, so edits take effect immediately and the offline
install needs no build backend.

---

## The knowledge graph

| Folder | Type | Holds |
| --- | --- | --- |
| `People/` | `person` | One per team member. Focus, 1:1s, growth, context. |
| `Sprints/` | `sprint` | Starts as your brief; Jira goal, workload, issues, plan and **Done by** are added below it. |
| `Projects/` | `epic` | Arcs spanning sprints. |
| `Decisions/` | `decision` | Context, decision, consequences. |
| `Meetings/` | `meeting` | Retros, planning, skip-levels. |
| `Topics/` | `topic` | Everything else. |

Edges are `[[wikilinks]]`. **A person's history is their backlinks** — every
sprint and decision that named them shows up on their page automatically,
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

- **Nothing is published without asking.** Creating a sprint, moving issues
  and publishing to Confluence are all visible to the team; the skills confirm
  first. GitLab is only ever read.
- **Sprints are sized on completed work, never committed.** Issue counts when
  the team doesn't estimate, points once it does.
- **Goals come before people's focus.** The brief's vectors decide what goes
  in; focus decides who does it, and conflicts are shown, not hidden.
- **1:1 and person notes stay local.** They are never published to Confluence or
  GitLab.
- **Secrets stay out of git.** `.env`, `config.toml` and `.mcp.json` are all
  ignored. When zipping the repo to carry it across, exclude `.env` explicitly —
  see [INSTALL.md](INSTALL.md#a4-zip-it).
