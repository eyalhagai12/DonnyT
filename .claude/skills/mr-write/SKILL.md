---
name: mr-write
description: Write a GitLab merge request description that follows the team's Confluence template. Use when opening an MR, drafting or rewriting an MR description, preparing a branch for review, or when the user says "write the MR", "open an MR", "MR description", or "merge request".
---

# Write a merge request from the Confluence template

The point of this skill is that MR descriptions match the template the team
agreed on in Confluence — not a shape invented fresh each time. Always fetch
the template; never write an MR description from memory of what it looks like.

## Steps

### 1. Fetch the template first

Call `confluence_get_mr_template`. It returns the template as Markdown plus its
section headings.

If it fails, stop and report the error — do not fall back to an invented
structure. A missing template usually means `confluence.mr_template_page_id` is
unset in `config.toml`; `donnyt_doctor` confirms it.

### 2. Gather the facts

Work out what actually changed. Prefer real evidence over the branch name:

- **Branch not yet pushed** → `gitlab_branch_summary` with the repo path.
  Gives commits, changed files and a diffstat from the local checkout.
- **Branch already on the server** → `gitlab_compare` with the source branch.
- **Existing MR being rewritten** → `gitlab_list_mrs`, then read its diff.

Then read the actual diff for anything you intend to describe. Commit
subjects say what someone *meant* to do; the diff says what they did. If those
disagree, describe the diff and say so.

### 3. Link the Jira issue

Branch names and MR titles usually carry the key (`TEAM-1234`). Pull it out and
call `jira_get_issue` to get the real summary, type and acceptance criteria.
Use those to fill the template's "what" and "why" sections.

If no key is present, ask the user which issue this belongs to rather than
leaving the field blank — an unlinked MR is the thing that breaks traceability
later.

### 4. Fill every section

Work through the template's sections in order and fill each one:

- Keep the template's exact headings, order and any checklists.
- Where a section genuinely does not apply, write `N/A — <one-line reason>`.
  Never silently drop a section, and never leave a placeholder hint in place.
- Convert checklist items to real state: tick what the diff shows is done,
  leave the rest unticked. Do not tick something you have not verified.
- Be concrete. "Refactored the service" is worthless; "split `OrderService`
  into `OrderReader`/`OrderWriter` so the read path can be cached" is a review
  someone can act on.

### 5. Show it before sending

Print the finished description and ask for confirmation before creating
anything. Opening an MR is visible to the whole team — confirm first.

### 6. Create or update

- New MR → `gitlab_create_mr`. Leave `draft: true` unless the user says
  otherwise.
- Existing MR → `gitlab_update_mr` with the `iid`.

### 7. Record it in the vault

After it exists, call `vault_sync_mr` with the MR's `iid` and a one-line
`summary`. That writes the MR note and links it to the author and the Jira
issue, so the decision trail survives past the merge.

## Notes

- Never invent issue keys, ticket numbers or reviewer names.
- If the diff touches auth, crypto, migrations or anything that deletes data,
  call it out explicitly in the description even when the template has no
  section for it.
- Large MRs: if the diff spans more than roughly 20 files or several unrelated
  concerns, say so and suggest splitting it. Mention it once; if the user wants
  it as one MR, write it as one MR.

## If the donnyt tools are not available

On a host where the `mcp` package could not be installed, the `donnyt_*`,
`jira_*`, `gitlab_*`, `confluence_*` and `vault_*` tools do not exist -- but
every one has an identical CLI command. Run `python -m donnyt.cli tools` for
the mapping, then use the commands through the shell (from the repo root, with
the repo's `.venv` Python). Same data, same rules: the confirm-before-sending
steps above apply unchanged. Pass long Markdown (MR descriptions, notes,
pages) with `--file <path>` rather than inline.
