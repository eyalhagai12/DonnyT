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

## 3. Tokens

Three admin tokens; `seed.py` creates everything else with them.

- **Jira**: Profile → **Personal Access Tokens** → create one.
- **Confluence**: Profile → **Personal Access Tokens** → create one. It is
  separate from Jira's.
- **GitLab** (as root): Avatar → **Edit profile** → **Access tokens** →
  scopes `api`, `read_repository`, `write_repository`. It must be an admin's:
  the seed creates users and tokens for the team.

Put them in `test/devstack/donnyt/.env` (git-ignored, like everything under
`donnyt/`):

```ini
JIRA_PAT=...
CONFLUENCE_PAT=...
GITLAB_TOKEN=glpat-...
```

## 4. Seed the team

```bash
python test/devstack/seed.py            # everything; safe to re-run, resets to the same state
python test/devstack/seed.py jira vault # or just some of it
```

It builds a small team making a **todo API in Go** (`todo/`), and resets:

| Where | What |
| --- | --- |
| GitLab `team/todo` | `main` = v0, one commit per ticket by its author (`todo/patches/`); a user and token per team member; no MRs or branches |
| Jira `TEAM` | 3 closed sprints that built v0, one spill-over, nothing estimated; 16 backlog features and bugs of deliberately mixed size |
| Confluence `ENG` | the PRD template, parent pages for plans and PRDs |
| `donnyt/vault` | a person note with role and Focus per member, the repo's templates, no sprint notes |
| `donnyt/config.toml` | board, fields, pages, `team/todo`, the roster, a Sun–Thu week |

`donnyt/config.toml` needs the addresses once; the seed fills in the rest:

```toml
[atlassian]
jira_url = "http://localhost:8080"
confluence_url = "http://localhost:8090"
deployment = "datacenter"

[confluence]
space = "ENG"

[jira]
project_key = "TEAM"
board_id = 0

[gitlab]
url = "http://localhost:8929"

[vault]
path = "vault"
```

Point DonnyT at it with `DONNYT_HOME=test/devstack/donnyt`, then
`python -m donnyt.cli doctor`.

## 5. Run a sprint

[SIMULATION.md](SIMULATION.md): plan a sprint from a brief with DonnyT, then
play the team through it with `team.py` -- real code, real MRs, real spill-over.

## Stopping

```bash
docker compose stop        # pause; resumes with `docker compose start`
docker compose down        # remove containers, keep data
docker compose down -v     # remove everything, including licences and data
```
