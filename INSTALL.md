# Installing DonnyT

Written for an **airtight internal network**: a machine with no access to
PyPI, GitHub or the public internet. Everything needed is carried in inside the
zip.

There are two roles. Read the one you are doing.

- **[Part A — Preparing the zip](#part-a--preparing-the-zip)** — on a machine
  *with* internet. Done once, by whoever packages it.
- **[Part B — Installing on the isolated machine](#part-b--installing-on-the-isolated-machine)**
  — no internet needed.

---

## Requirements

### On the isolated machine

| | Requirement | Why | How to check |
| --- | --- | --- | --- |
| **Required** | **Python 3.11 or newer** | Config is read with `tomllib`, added in 3.11 | `python --version` |
| **Required** | Network access to your **Jira/Confluence** host | Reading sprints and templates | `curl -I https://your-team.atlassian.net` |
| **Required** | Network access to your **GitLab** host | Reading and creating MRs | `curl -I https://gitlab.internal.corp` |
| **Required** | **Claude Code** | Runs the skills and the MCP server | `claude --version` |
| Optional | **git** | Reading local branches for MR descriptions | `git --version` |
| Optional | **Obsidian** | Viewing the knowledge graph. The vault is plain Markdown and works without it | — |

> **No internet is required**, but the machine *must* reach your internal Jira,
> Confluence and GitLab hosts. This toolkit talks to those over HTTPS. If they
> are unreachable, nothing here can work.

### Credentials you will need

Have these in hand before you start. Both are created through a web UI, so get
them from a machine that can reach the relevant site.

| Credential | Where to create it | Scopes / permissions |
| --- | --- | --- |
| **Atlassian API token** (covers both Confluence and Jira) | `https://id.atlassian.com/manage-profile/security/api-tokens` → **Create API token** | Inherits your own permissions. You must be able to see the board and the template page. |
| **GitLab personal access token** | `<your-gitlab>/-/user_settings/personal_access_tokens` | **`api`** and **`read_repository`** |

> The Atlassian token is shown **once**. Copy it immediately.
>
> Self-hosted Jira/Confluence (Data Center, not Cloud) uses a Personal Access
> Token from your profile instead — see [Troubleshooting](#troubleshooting).

### Ids you will need

Collect these before step 5; each is visible in a URL.

| Setting | Where to find it | Example |
| --- | --- | --- |
| `atlassian.site` | Address bar on any Jira or Confluence page | `https://acme.atlassian.net` |
| `confluence.space` | Page URL: `/wiki/spaces/`**`ENG`**`/pages/...` | `ENG` |
| `confluence.mr_template_page_id` | Page URL: `/pages/`**`123456789`**`/MR+Template` | `123456789` |
| `jira.project_key` | The prefix on any issue: **`TEAM`**`-1234` | `TEAM` |
| `jira.board_id` | Board URL: `/boards/`**`42`** | `42` |
| `gitlab.default_project` | The path after the host | `platform/backend/api` |

If you get `jira.board_id` wrong, `donnyt doctor` lists the valid ids for you.

---

## Part A — Preparing the zip

Do this **on a machine with internet access**.

### A1. Get the repo onto that machine

```bash
git clone <this-repo> DonnyT
cd DonnyT
```

### A2. Download the dependencies

```bash
python scripts/build_offline_bundle.py
```

This fills `vendor/wheels/` with the `mcp` package and its dependency tree
(~30 packages, ~15 MB) and writes a `MANIFEST.txt` recording what was bundled
and for which platform.

> **Wheels are platform-specific.** If the isolated machine runs a different OS
> or Python version than this one, say so explicitly:
>
> ```bash
> # isolated machine is Windows on Python 3.11
> python scripts/build_offline_bundle.py --platform win_amd64 --python-version 3.11
>
> # isolated machine is Linux on Python 3.11
> python scripts/build_offline_bundle.py --platform manylinux2014_x86_64 --python-version 3.11
> ```

### A3. Prove the bundle works offline

```bash
python scripts/build_offline_bundle.py --check
```

This installs the bundle with `--no-index` into a throwaway virtual
environment. It must print `offline bundle OK`. Do not ship a bundle that
fails this check — you will not get a second chance once it is across.

### A4. Zip it

Include `vendor/wheels/`. Exclude anything machine-specific and anything
secret:

```bash
# from the parent directory
zip -r DonnyT.zip DonnyT \
    -x "DonnyT/.git/*" "DonnyT/.venv/*" "DonnyT/.env" \
       "DonnyT/config.toml" "DonnyT/.mcp.json" \
       "DonnyT/**/__pycache__/*"
```

PowerShell:

```powershell
Get-ChildItem DonnyT -Recurse -Force |
  Where-Object { $_.FullName -notmatch '\\(\.git|\.venv|__pycache__)\\' -and
                 $_.Name -notin '.env','config.toml','.mcp.json' } |
  Compress-Archive -DestinationPath DonnyT.zip
```

> **Never ship `.env`.** It holds live API tokens. It is in `.gitignore`, but a
> zip of the working directory will pick it up unless excluded. Check before
> you hand the file over.

---

## Part B — Installing on the isolated machine

No internet required.

### Step 1 — Check Python

```bash
python --version
```

Must be **3.11 or newer**. If it is older, or missing, install Python 3.11+
through whatever channel your organisation provides. Nothing else here will
work first.

If Python is installed but not on `PATH`, note its full path — you will pass it
in step 3.

### Step 2 — Unzip

Put it somewhere stable. You will point Claude Code at this folder, and the
path is written into `.mcp.json`, so moving it later means re-running the
installer.

```
C:\Users\<you>\Projects\DonnyT          # Windows
~/projects/DonnyT                        # macOS / Linux
```

### Step 3 — Run the installer

**Windows (PowerShell):**

```powershell
cd C:\Users\<you>\Projects\DonnyT
.\install.ps1
```

If PowerShell blocks the script:

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

If Python is not on `PATH`:

```powershell
.\install.ps1 -Python "C:\Python311\python.exe"
```

**macOS / Linux:**

```bash
cd ~/projects/DonnyT
chmod +x install.sh
./install.sh
```

The installer:

1. finds Python 3.11+,
2. creates `.venv`,
3. installs `mcp` from `vendor/wheels` with **no network access**,
4. links `src/` into the environment, so your edits to this repo take effect
   with no reinstall,
5. copies `.env.example` → `.env` and `config.example.toml` → `config.toml`
   (**never overwriting** ones that already exist),
6. generates `.mcp.json` so Claude Code can start the server,
7. runs the doctor.

It is safe to re-run at any time. Add `-Force` / `--force` to rebuild `.venv`
from scratch.

**Expect it to report failures at this point.** You have not entered any
credentials yet. That is steps 4 and 5.

### Step 4 — Add your credentials

Open `.env` and fill in the three values:

```ini
ATLASSIAN_EMAIL=you@yourcompany.com
ATLASSIAN_API_TOKEN=ATATT3xFfGF0...
GITLAB_TOKEN=glpat-xxxxxxxxxxxxxxxxxxxx
```

Where these come from is in [Credentials](#credentials-you-will-need) above.

If your network intercepts TLS or requires a proxy, uncomment and set those
values too — the file explains each one.

> `.env` is listed in `.gitignore` and is never committed. On macOS/Linux the
> installer also sets its permissions to `600`.

### Step 5 — Configure your team

Open `config.toml`. Every field is commented in place with where to find its
value. At minimum set:

```toml
[atlassian]
site = "https://acme.atlassian.net"

[confluence]
space = "ENG"
mr_template_page_id = "123456789"   # your MR template page

[jira]
project_key = "TEAM"
board_id = 42

[gitlab]
url = "https://gitlab.internal.corp"
default_project = "platform/backend/api"
```

Then list your team. This drives capacity planning and connects Jira and GitLab
identities to the person notes in the vault:

```toml
[[team.members]]
name = "Maya Cohen"        # MUST match their Jira display name exactly
jira = "5f8a1c2d3e4b5a6c"  # accountId
gitlab = "mcohen"
capacity = 8               # story points per full sprint
```

Find a Jira `accountId` at:
`<site>/rest/api/3/user/search?query=their@email.com`

> `name` must match the Jira display name **exactly**, or assignees will not
> resolve to the right person note.

### Step 6 — Verify

```powershell
.\.venv\Scripts\python.exe -m donnyt.cli doctor      # Windows
```
```bash
./.venv/bin/python -m donnyt.cli doctor              # macOS / Linux
```

Every check should pass:

```
[ok]   python           Python 3.11.9
[ok]   repo_root        C:\Users\you\Projects\DonnyT  (auto-detected)
[ok]   .env             found
[ok]   config.toml      found
[ok]   mcp_package      usable (MCPServer)
[ok]   config           config.toml parsed
[ok]   confluence       authenticated as You; MR template 'Merge Request Template' (id 123456789)
[ok]   jira             board 42 'TEAM board'; active sprint 'Sprint 14'
[ok]   gitlab           authenticated as @you; project platform/backend/api
[ok]   vault            1 notes at ...\vault
```

Each failure names the exact setting or credential at fault. Work through them
before moving on — see [Troubleshooting](#troubleshooting).

### Step 7 — Connect Claude Code

```bash
cd /path/to/DonnyT
claude
```

Claude Code finds `.mcp.json` and asks to approve the `donnyt` MCP server.
Approve it. Confirm with `/mcp` — you should see `donnyt` connected with 28
tools.

Then try:

```
/sprint-plan
```

### Step 8 — Open the vault in Obsidian (optional)

**Open folder as vault** → select `DonnyT/vault`.

Graph view is `Ctrl/Cmd+G`. Nodes are coloured by type: people blue, sprints
green, MRs orange, decisions purple.

The vault is plain Markdown. Skipping Obsidian costs you the graph view and
nothing else.

---

## Troubleshooting

Run `donnyt doctor` first. It names the failing setting. Beyond that:

### `CERTIFICATE_VERIFY_FAILED`

Your network re-signs TLS traffic with a private CA. Get your organisation's
root certificate as a `.pem` and point `.env` at it:

```ini
DONNYT_CA_BUNDLE=C:\certs\corporate-root-ca.pem
```

Last resort only, if the certificate cannot be obtained:

```ini
DONNYT_INSECURE_TLS=true
```

That disables certificate verification for every request this toolkit makes.
Use it to confirm a diagnosis, then get the real certificate.

### `Could not reach ...` / connection timed out

The host is blocked or needs a proxy. Set it in `.env`:

```ini
HTTPS_PROXY=http://proxy.internal.corp:8080
NO_PROXY=localhost,127.0.0.1,.internal.corp
```

Confirm the host is reachable at all before blaming the toolkit:

```bash
curl -I https://your-team.atlassian.net
```

### Offline install failed / `No matching distribution found`

The bundle does not match this machine. Check
`vendor/wheels/MANIFEST.txt` — it records the target platform and Python
version it was built for. Rebuild it on a connected machine with matching
`--platform` and `--python-version` (Part A, step A2).

### `HTTP 401` from Confluence or Jira

The token is wrong, expired, or paired with the wrong email. `ATLASSIAN_EMAIL`
must be the account the token was minted under. Regenerate and re-paste —
tokens are easy to truncate on copy.

### `HTTP 403` from GitLab

The token lacks the `api` scope, or your account cannot see that project.
Regenerate with both `api` and `read_repository`.

### `HTTP 404` on the MR template

`confluence.mr_template_page_id` is wrong, or your account cannot see the page.
Open the page in a browser while signed in as the token's owner and re-copy the
numeric id from the URL.

### Story points always come back `null`

`jira.story_points_field` does not match your site. Find the right id:

```
<site>/rest/api/3/issue/TEAM-1234?fields=*all
```

Look for the custom field holding the point value and put its id in
`config.toml`.

### Self-hosted Jira / Confluence (Data Center)

The REST paths differ from Cloud. `src/donnyt/confluence.py` and
`src/donnyt/jira.py` target the Cloud APIs (`/wiki/api/v2`, `/rest/api/3`,
`/rest/agile/1.0`). Data Center uses `/rest/api/content` and has no
`/rest/api/3`. Adapting is a contained change in those two files.

### Claude Code does not see the server

1. Is `.mcp.json` present? The installer generates it — re-run if not.
2. Does the `command` path in it exist?
3. Was the server approved? Check `/mcp`.
4. Did you start `claude` from the repo directory?

The `DONNYT_HOME` value in `.mcp.json` pins the repo location, so the server
finds `config.toml` regardless of where Claude Code is launched from. If you
move the folder, re-run the installer.

### Nothing works and you need to get going

The CLI needs no MCP package at all — it is pure standard library:

```bash
python -m donnyt.cli doctor
python -m donnyt.cli template
python -m donnyt.cli velocity
python -m donnyt.cli sync
```

`python -m donnyt.cli --help` lists everything.

---

## Updating an installed copy

1. Copy the new `src/` and `.claude/` over the old ones.
2. Re-run the installer — it will not touch your `.env` or `config.toml`.

Because `src/` is linked rather than installed, code changes take effect
immediately. Only a change to the `mcp` dependency needs a fresh bundle.

## Uninstalling

Delete the folder. Nothing is installed outside it. Then revoke the two API
tokens at the URLs in [Credentials](#credentials-you-will-need).
