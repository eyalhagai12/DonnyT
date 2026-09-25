# Local Data Center test stack

Real Jira and Confluence Data Center plus GitLab CE in Docker, so DonnyT can be
tested against self-hosted APIs before it goes onto the internal network.

Needs Docker (Docker Desktop on Windows/macOS) with about 10 GB of memory for
containers. Everything binds to `127.0.0.1` only.

| Service | URL | Login |
| --- | --- | --- |
| Jira | http://localhost:8080 | the admin you create in the wizard |
| Confluence | http://localhost:8090 | the admin you create in the wizard |
| GitLab | http://localhost:8929 | `root` / `DonnyT-devstack-2026` |

## 1. Start it

```bash
cd test/devstack
cp .env.example .env        # optional: set versions to match the internal instances
docker compose up -d
docker compose ps           # wait until jira, confluence and gitlab are up
```

First boot takes 5–10 minutes; GitLab is the slowest.

## 2. Licence Jira and Confluence (free, 30 days)

Each product asks for a licence on first visit. The database is already wired
up, so the licence is the only thing the wizards really need.

1. Open http://localhost:8080. Pick **I'll set it up myself** if asked. The
   licence page shows a **Server ID** (`XXXX-XXXX-XXXX-XXXX`).
2. Go to https://my.atlassian.com/license/evaluation (sign in with any
   Atlassian account) → **Jira Software** → **Data Center** → paste the Server
   ID → **Generate licence**.
3. Paste the licence into the wizard, then create the admin user. Skip email
   setup.
4. Repeat for Confluence at http://localhost:8090 (product **Confluence**,
   **Data Center**). Choose **Example site** or **Empty site**, then create
   the admin — or pick "manage users with Jira" only if you want them linked.

After 30 days the licences expire and Jira and Confluence go read-only. Either
paste a fresh evaluation licence in admin → licensing, or `docker compose down -v`
and start over.

## 3. Create what DonnyT needs

**Jira** (as admin)
- Create a **Scrum** project with key `TEAM`. Note the board id in the board
  URL (`rapidView=1` or `/boards/1`).
- Add a few issues with story points, run 3–4 sprints and close them — leave one
  issue unfinished so it spills over.
- Profile → **Personal Access Tokens** → create one.

**Confluence** (as admin)
- Create a space with key `ENG`, and a page copying your MR template's
  *structure* (headings, tables, checklists, the same macros) with made-up text.
  Note its id: **⋯ → Page Information**, `pageId=` in the URL.
- Profile → **Personal Access Tokens** → create one. It is separate from Jira's.

**GitLab** (as root)
- Create a project, e.g. `team/api`, and push a branch like `TEAM-1-something`.
- Avatar → **Edit profile** → **Access tokens** → scopes `api`, `read_repository`.

## 4. Point DonnyT at it

`config.toml`:

```toml
[atlassian]
jira_url = "http://localhost:8080"
confluence_url = "http://localhost:8090"
deployment = "datacenter"

[confluence]
space = "ENG"
mr_template_page_id = "<page id>"

[jira]
project_key = "TEAM"
board_id = <board id>
story_points_field = "customfield_10106"   # doctor tells you the right one

[gitlab]
url = "http://localhost:8929"
default_project = "team/api"
```

`.env`:

```ini
JIRA_PAT=...
CONFLUENCE_PAT=...
GITLAB_TOKEN=glpat-...
```

Then `python -m donnyt.cli doctor` and work through `INTERNAL_SETUP.md`.

## Stopping

```bash
docker compose stop        # pause; resumes with `docker compose start`
docker compose down        # remove containers, keep data
docker compose down -v     # remove everything, including licences and data
```
