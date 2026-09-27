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
| **Required** | Network access to your **Jira/Confluence** hosts. Cloud or self-hosted Data Center both work | Reading sprints and templates | `curl -I https://jira.yourcompany.internal` |
| **Required** | Network access to your **GitLab** host | Reading merged work and reviews (read-only) | `curl -I https://gitlab.internal.corp` |
| **Required** | **Claude Code** | Runs the skills | `claude --version` |
| Optional | **Obsidian** | Viewing the knowledge graph. The vault is plain Markdown and works without it | — |
| Optional | The **`mcp`** Python package, from the zip's bundle *or* an internal package mirror | Exposes the tools to Claude Code as MCP tools. **Without it everything still works** through the CLI | — |

> **You do not need to know in advance what the internal network has.** The
> installer tries the bundled wheels, then an internal package mirror, and if
> neither provides `mcp` it installs in **CLI-only mode**: every tool is then
> `python -m donnyt.cli <command>`, and the skills switch to that on their own.

> **No internet is required**, but the machine *must* reach your internal Jira,
> Confluence and GitLab hosts. This toolkit talks to those over HTTPS. If they
> are unreachable, nothing here can work.

### Credentials you will need

Have these in hand before you start. Both are created through a web UI, so get
them from a machine that can reach the relevant site.

| Credential | Where to create it | Scopes / permissions |
| --- | --- | --- |
| **Atlassian Cloud:** API token (covers both Confluence and Jira) | `https://id.atlassian.com/manage-profile/security/api-tokens` → **Create API token** | Inherits your own permissions. You must be able to see the board and the template page. |
| **Atlassian Data Center:** personal access token(s) | In Jira and in Confluence: avatar → **Profile** → **Personal Access Tokens** | Inherits your permissions. Jira and Confluence each issue their own. |
| **GitLab personal access token** | `<your-gitlab>/-/user_settings/personal_access_tokens` | **`read_api`** and **`read_repository`** — DonnyT only reads |

> Tokens are shown **once**. Copy them immediately.
>
> Not sure which Atlassian you have? If the address ends in `.atlassian.net`,
> it is Cloud. Anything else (`jira.yourcompany.internal`, an IP address, a
> `/jira` path) is Data Center.

### Ids you will need

Collect these before step 5; each is visible in a URL.

| Setting | Where to find it | Example |
| --- | --- | --- |
| `atlassian.site` | Address bar on any Jira page | `https://acme.atlassian.net` or `https://jira.corp.internal` |
| `atlassian.confluence_url` | Data Center only, when Confluence has its own host or path | `https://wiki.corp.internal` |
| `confluence.space` | Page URL: `/spaces/`**`ENG`**`/...`, or `spaceKey=ENG` | `ENG` |
| `confluence.prd_template_page_id` | Optional, for `/prd-write`. Cloud page URL: `/pages/`**`123456790`**`/PRD+Template`. Data Center: **⋯ → Page Information**, the `pageId=` in the URL | `123456790` |
| `jira.project_key` | The prefix on any issue: **`TEAM`**`-1234` | `TEAM` |
| `jira.board_id` | Board URL: `/boards/`**`42`** | `42` |
| `gitlab.default_project` | One repo: the path after the host. Several: list them as `[[gitlab.repos]]` instead (step 5) | `platform/backend/api` |

If you get `jira.board_id` wrong, `donnyt doctor` lists the valid ids for you.

---

## Part A — Preparing the zip

Do this **on a machine with internet access**.

### A1. Get the repo onto that machine

```bash
git clone <this-repo> DonnyT
cd DonnyT
```

### A2. Download the dependencies (optional, recommended)

The bundle lets the MCP server install with no network at all. It is optional:
without it, the installer tries an internal package mirror, then falls back to
CLI-only mode. It is still the one route that needs nothing from the inside.

**Don't know the isolated machine's OS or Python version?** Bundle for all the
likely ones. pip picks the matching wheels at install time:

```bash
python scripts/build_offline_bundle.py --clean --preset common
```

`common` covers Windows and Linux (x86-64) on Python 3.11, 3.12 and 3.13.
`--preset windows` or `--preset linux` narrow it. If you do know the target,
name it. A target is `PLATFORM[,PLATFORM...]:PYTHON_VERSION`:

```bash
python scripts/build_offline_bundle.py --clean --target win_amd64:3.11
```

This fills `vendor/wheels/` and writes a `MANIFEST.txt` recording the targets.

### A3. Prove the bundle works offline

```bash
python scripts/build_offline_bundle.py --check
```

This installs the bundle with `--no-index` into a throwaway virtual
environment (when it fits this machine), then proves every target in the
manifest resolves offline. Every target line must read `OK`. Do not ship a
bundle that fails this check.

### A4. Zip it

Include `vendor/wheels/`. Exclude anything machine-specific and anything
secret. Zip the fresh clone from A1, not a working copy you have developed in:
a working copy also holds the local test stack's credentials, vault and
generated mockups under `test/devstack/`.

```bash
# from the parent directory
zip -r DonnyT.zip DonnyT \
    -x "DonnyT/.git/*" "DonnyT/.venv/*" "DonnyT/.env" \
       "DonnyT/config.toml" "DonnyT/.mcp.json" "DonnyT/.mcp.json.*" \
       "DonnyT/test/devstack/.env" "DonnyT/test/devstack/donnyt/*" \
       "DonnyT/ui-style/*" "DonnyT/mocks/*" "DonnyT/.donnyt/*" \
       "DonnyT/**/__pycache__/*"
```

PowerShell:

```powershell
Get-ChildItem DonnyT -Recurse -Force |
  Where-Object { $_.FullName -notmatch '\\(\.git|\.venv|__pycache__|\.donnyt|ui-style|mocks)\\' -and
                 $_.FullName -notmatch '\\test\\devstack\\donnyt\\' -and
                 $_.Name -notin '.env','config.toml','.mcp.json' -and
                 $_.Name -notlike '.mcp.json.*' } |
  Compress-Archive -DestinationPath DonnyT.zip
```

> **Never ship `.env`.** The one at the root holds live API tokens, and so do
> `test/devstack/.env` and `test/devstack/donnyt/.env`. They are in
> `.gitignore`, but a zip of the working directory picks them up unless
> excluded. List the zip's contents before you hand the file over.

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

**If the internal network has a package mirror** (Artifactory, Nexus, devpi…),
point the installer at it. It is only used if the bundle doesn't fit:

```powershell
.\install.ps1 -IndexUrl https://artifactory.corp/api/pypi/pypi/simple
```
```bash
./install.sh --index-url https://artifactory.corp/api/pypi/pypi/simple
```

If pip on that machine is already set up for the mirror (`pip.ini` /
`pip.conf`, or `PIP_INDEX_URL`), you don't need to pass anything. For a mirror
behind a private CA, set `PIP_CERT` to the CA file first.

| `-Source` / `--source` | Behaviour |
| --- | --- |
| `auto` (default) | Bundle, then mirror, then CLI-only. Never fails for want of `mcp`. |
| `bundle` | Bundle only; fail if it doesn't fit. |
| `index` | Mirror only; fail if it doesn't have `mcp`. |
| `none` | Skip `mcp`; CLI-only. |

The installer:

1. finds Python 3.11+,
2. creates `.venv`,
3. installs `mcp` from the bundle or the mirror. If neither has it, it
   continues in **CLI-only mode** and says so,
4. links `src/` into the environment, so your edits to this repo take effect
   with no reinstall,
5. copies `.env.example` → `.env` and `config.example.toml` → `config.toml`
   (**never overwriting** ones that already exist),
6. generates `.mcp.json` so Claude Code can start the server (skipped in
   CLI-only mode, because a server that can't start is worse than none),
7. runs the doctor.

It is safe to re-run at any time. Add `-Force` / `--force` to rebuild `.venv`
from scratch.

**Expect it to report failures at this point.** You have not entered any
credentials yet. That is steps 4 and 5.

### Step 4 — Add your credentials

Open `.env`. For **Atlassian Cloud**:

```ini
ATLASSIAN_EMAIL=you@yourcompany.com
ATLASSIAN_API_TOKEN=ATATT3xFfGF0...
GITLAB_TOKEN=glpat-xxxxxxxxxxxxxxxxxxxx
```

For **Data Center**, use a personal access token instead. Either one shared
value, or one per product if Jira and Confluence issued different tokens:

```ini
ATLASSIAN_PAT=NjM4OTk...          # or JIRA_PAT=... and CONFLUENCE_PAT=...
GITLAB_TOKEN=glpat-xxxxxxxxxxxxxxxxxxxx
```

An old Server install without personal access tokens can use basic auth:
`ATLASSIAN_USERNAME`, plus your password in `ATLASSIAN_API_TOKEN`.

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
site = "https://acme.atlassian.net"     # or https://jira.corp.internal

[confluence]
space = "ENG"
prd_template_page_id = ""            # optional: your PRD template page, for /prd-write

[jira]
project_key = "TEAM"
board_id = 42

[gitlab]
url = "https://gitlab.internal.corp"
default_project = "platform/backend/api"
```

**The team works in several repos?** List each one, with the Jira components
or labels whose tickets touch it. A ticket's components then decide which
repos `/estimate` reads, and every repo's merged work counts in "Done by":

```toml
[[gitlab.repos]]
project = "platform/backend/api"
jira = ["api", "backend"]        # Jira components or labels; leave it out = every ticket

[[gitlab.repos]]
project = "platform/web"
jira = ["web"]
```

`doctor` checks it can read every repo, and names any Jira component that no
repo claims — tickets with only those components get "which repos?" asked
about them instead of guessed.

**Data Center with Confluence on its own host or path?** Add:

```toml
[atlassian]
site = "https://jira.corp.internal"
confluence_url = "https://wiki.corp.internal"     # or https://corp.internal/confluence
```

`deployment = "auto"` works out Cloud vs Data Center from the address. Set it
to `"cloud"` or `"datacenter"` only if the doctor gets it wrong.

Then list your team. This connects Jira and GitLab identities to the person
notes in the vault, and records who did what in each sprint:

```toml
[[team.members]]
name = "Maya Cohen"        # MUST match their Jira display name exactly
jira = "5f8a1c2d3e4b5a6c"  # Cloud accountId, or Data Center username
gitlab = "mcohen"          # their GitLab username: how merged work is credited
# capacity = 8             # optional: story points per full sprint, only if the team estimates
```

Find a Cloud `accountId` at `<site>/rest/api/3/user/search?query=their@email.com`.
On Data Center it is the username shown on their profile.

> `name` must match the Jira display name **exactly**, or assignees will not
> resolve to the right person note.

If your week is not Monday to Friday, say so. Sprint briefs count working days
from it:

```toml
[team]
weekend = ["Fri", "Sat"]   # default ["Sat", "Sun"]
```

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
[ok]   atlassian        datacenter (auto-detected); jira https://jira.corp.internal; confluence https://wiki.corp.internal; auth personal access token
[ok]   confluence       authenticated as You; PRD template 'PRD Template' (id 123456790)
[ok]   jira             board 42 'TEAM board'; active sprint 'Sprint 14'; points field customfield_10002 (Story Points)
[ok]   gitlab           authenticated as @you; project platform/backend/api
[ok]   vault            1 notes at ...\vault
```

In CLI-only mode, `mcp_package` reads `[--]` (skipped) instead of `[ok]`. That
is fine. Each failure names the exact setting or credential at fault. Work
through them before moving on. See [Troubleshooting](#troubleshooting).

### Step 7 — Connect Claude Code

```bash
cd /path/to/DonnyT
claude
```

Claude Code finds `.mcp.json` and asks to approve the `donnyt` MCP server.
Approve it. Confirm with `/mcp` — you should see `donnyt` connected with 28
tools.

**CLI-only mode:** there is no server to approve. The skills notice the tools
are missing and run `python -m donnyt.cli` commands instead; allow them when
Claude Code asks. `python -m donnyt.cli tools` lists every command.

Then try:

```
/sprint-plan
```

### Step 8 — Open the vault in Obsidian (optional)

**Open folder as vault** → select `DonnyT/vault`.

Graph view is `Ctrl/Cmd+G`. Nodes are coloured by type: people blue, sprints
green, decisions purple.

The vault is plain Markdown. Skipping Obsidian costs you the graph view and
nothing else.

### Step 9 — UI mockups (optional)

`/ui-mock` (and the Mockups section of `/prd-write`) draws screens in the style
of your own system. It needs only a browser that is already installed: Edge
ships with Windows; on Linux or macOS, Chrome or Chromium. No package to
install.

1. `python -m donnyt.cli doctor` should show `[ok] ui_mockups  browser ...`.
   It uses your default browser when that is Chrome or Edge. To choose, set
   `ui.browser` in `config.toml` to `"chrome"` or `"edge"`, or to the full
   path of the executable.
2. Give it the look of your system, either or both:
   - **Screenshots:** save a few PNGs of typical pages (a list, a form, a
     detail page) into `ui-style/screens/`. Optionally write
     `ui-style/style.md` with exact colours, fonts and conventions; it wins
     over what is guessed from the pixels.
   - **The running app:** `python -m donnyt.cli ui-capture <url> <name>`.
     If the result shows a login page, run
     `python -m donnyt.cli ui-login <url>` once, sign in (tick *Remember me*),
     close the window, and capture again.

`ui-style/`, `mocks/` and `.donnyt/` are git-ignored: screenshots of internal
apps can contain real data.

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

### `The bundle does not fit this machine` / `No matching distribution found`

The bundle was built for other Python versions or operating systems;
`vendor/wheels/MANIFEST.txt` lists its targets. With the default
`-Source auto` this isn't fatal: the installer moves on to the mirror, then to
CLI-only mode. To get the MCP server, either point the installer at a mirror
(`-IndexUrl`), or rebuild the bundle with `--preset common` or a matching
`--target` (Part A, step A2).

### `HTTP 401` from Confluence or Jira

**Cloud:** the token is wrong, expired, or paired with the wrong email.
`ATLASSIAN_EMAIL` must be the account the token was minted under. Regenerate
and re-paste; tokens are easy to truncate on copy.

**Data Center:** the personal access token is wrong or expired, or one
product's token is being used for both. Jira and Confluence issue separate
tokens, so set `JIRA_PAT` and `CONFLUENCE_PAT`. If PATs are disabled on your
instance, use basic auth instead: `ATLASSIAN_USERNAME`, your password in
`ATLASSIAN_API_TOKEN`, and `atlassian.auth = "basic"`.

### `HTTP 404` from Jira or Confluence on every call

Either the wrong API flavour or a missing context path. Check the doctor's
`atlassian` line:

- It says `cloud` but you are self-hosted: set `atlassian.deployment = "datacenter"`.
- Confluence lives under a path (`https://corp.internal/confluence`) or on
  another host: set `atlassian.confluence_url` to the address you open in a
  browser, without the page part. The same goes for `atlassian.jira_url`.

### `HTTP 403` from GitLab

The token lacks the `read_api` scope, or your account cannot see that project.
Regenerate with both `read_api` and `read_repository`.

### `HTTP 404` on the PRD template

`confluence.prd_template_page_id` is wrong, or your account cannot see the page.
Open the page in a browser while signed in as the token's owner and re-copy the
numeric id from the URL.

### Story points always come back `null`

`jira.story_points_field` does not match your site. The doctor checks this and
suggests the likely field. To look it up yourself, open
`<site>/rest/api/2/field` (Data Center) or `<site>/rest/api/3/field` (Cloud)
and search the page for "Story Points".

### Claude Code shows `donnyt` as failed

The server can't start, usually because `mcp` was removed or `.venv` was
rebuilt without it. Re-run the installer. In CLI-only mode it removes
`.mcp.json`, so the skills fall back to the CLI.

### Claude Code does not see the server

1. Is `.mcp.json` present? The installer generates it — re-run if not.
2. Does the `command` path in it exist?
3. Was the server approved? Check `/mcp`.
4. Did you start `claude` from the repo directory?

The `DONNYT_HOME` value in `.mcp.json` pins the repo location, so the server
finds `config.toml` regardless of where Claude Code is launched from. If you
move the folder, re-run the installer.

### Nothing works and you need to get going

The CLI needs no MCP package at all. It is pure standard library, and it
covers every tool:

```bash
python -m donnyt.cli doctor
python -m donnyt.cli template
python -m donnyt.cli velocity
python -m donnyt.cli sync
```

`python -m donnyt.cli tools` maps each MCP tool to its command, and
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
