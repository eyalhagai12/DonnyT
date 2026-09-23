# Internal setup runbook

For running this repo's setup on the isolated network, with a Claude model
that has **not** seen this codebase before and is **weaker** than the one that
built it. This document is written to be followed literally, one step at a
time, by that model (or by you, reading over its shoulder).

**Nothing about your Confluence template, your Jira data, or your team needs
to leave this network.** Every verification step in this document compares
things *locally* — the converted Markdown against the source page, open
side by side in a browser you're already signed into. That is the whole point
of this file: it replaces "paste the template to Claude and ask if it looks
right" with "run this command, look at two things next to each other, follow
the checklist."

---

## How to use this file

If you're pasting a first message into the internal Claude Code session, paste
this:

> Read `INTERNAL_SETUP.md` in this repo and follow it top to bottom, one
> numbered step at a time. After each step, show me the output and wait for
> me to say "continue" before moving to the next one. Do not skip the
> verification checklists — they exist because this template's exact
> structure was never seen by whoever wrote this repo. If a check fails,
> follow the "If this fails" instructions under that step exactly; do not
> improvise a fix. Never run anything under "Step 8" or later until every
> check before it has passed.

Each step below has:
- **Run** — the exact command.
- **Expect** — what a passing result looks like.
- **If this fails** — what to do, concretely, with no judgment calls left
  open where avoidable.

---

## Step 0 — Confirm the basic install is done

**Run:**
```
python -m donnyt.cli doctor
```

**Expect:** every line reads `[ok]` except possibly `tls_ca_bundle` and
`proxy`, which read `[--]` (skipped) and are fine to skip if your network
doesn't need them.

**If this fails:** stop here and work through `INSTALL.md` first — steps 1
through 6. Do not continue past this document until `doctor` is fully green.
Each `[FAIL]` line names the exact file and setting to fix.

---

## Step 1 — Get the raw template, unmodified

This is the one step that touches the actual template content, and it never
sends that content anywhere — it prints it to your own terminal, on your own
network.

**Run:**
```
python -m donnyt.cli template --raw
```

**Expect:** a block of XHTML starting with something like
`<h2>...</h2><p>...` and containing tags starting with `ac:` or `ri:` — that
prefix is Confluence's own macro namespace (`ac:structured-macro`,
`ac:placeholder`, `ac:task-list`, and so on). Seeing those tags is normal and
expected; do not try to "clean" this output, it is the ground truth.

**If this fails:**
- `error: not_found` or a 404 — `confluence.mr_template_page_id` in
  `config.toml` is wrong, or `confluence.mr_template_title` doesn't match the
  page's title exactly. Open the template page in your browser, copy the
  numeric id from the URL (`/pages/`**`123456789`**`/...`), and put that
  exact number in `config.toml`.
- `HTTP 403` — the account behind `ATLASSIAN_API_TOKEN` cannot see that page.
  Confirm you can open it yourself, signed in as that same account.
- Anything else — run `python -m donnyt.cli doctor` again; the `confluence`
  line will usually explain it.

**Save this output.** Copy it into a scratch file on your own machine (not
committed anywhere) — you'll compare against it in Step 2.

---

## Step 2 — Get the converted Markdown, and compare

**Run:**
```
python -m donnyt.cli template
```

**Expect:** readable Markdown — `##` headings, `-` bullets, tables using `|`,
checkboxes as `- [ ]`, and any Confluence macro (info panels, status labels,
expand sections) rendered as a line like `[Info]` or `[Status: Ready]`
followed by whatever text that macro contained.

**Now do the actual check — this is the important part:**

1. Open the real template page in Confluence, in your browser.
2. Open the Markdown output from this command side by side.
3. Go section by section down the Confluence page. For **every** section,
   heading, table, checklist, and callout box on the real page, find its
   counterpart in the Markdown. Tick each one off mentally.

**Checklist — the Markdown output must have:**

- [ ] Every heading from the real page, in the same order.
- [ ] Every table, with the same columns and rows.
- [ ] Every checklist item, as `- [ ]` or `- [x]`.
- [ ] Every info/warning/note/panel box — even if it just shows up as a
      `[Info]`-style tag plus its text, the **text itself** must be there.
- [ ] Every placeholder / instruction hint (the italic "describe X here"
      text authors leave in templates) — shown in the Markdown as `_italic_`.
- [ ] No section is silently missing. (A section that legitimately has no
      content is fine to be short — but it must still appear as a heading.)

**If anything is missing or garbled, go to Step 3. If the checklist is fully
satisfied, skip to Step 4.**

---

## Step 3 — Fix a conversion gap

Only do this if Step 2's checklist found something wrong. Work through these
in order — most problems are one of the first two.

### 3a. A whole section or macro's text vanished

Find the matching piece in the **raw XHTML** you saved in Step 1. Look for an
`<ac:structured-macro ac:name="...">` tag wrapping it and note the exact value
of `ac:name="..."`.

Open `src/donnyt/_html2md.py`. Find this function (search for
`def _preprocess_confluence`). Inside it there is a generic handler for
`ac:structured-macro` that already keeps most macro content — but if the
macro you found has an unusual internal shape (nested macros, a body under a
parameter name other than `title`), it can still slip through.

**Concretely:** add a special case just above the generic `macro()` function's
`return` lines, matching on the macro name you found. Example — say the macro
is `ac:name="rollout-checklist"` and its content lives directly under the
`<ac:structured-macro>` tag rather than inside `<ac:rich-text-body>`:

```python
# Add near the top of _preprocess_confluence, before the generic
# ac:structured-macro regex substitution runs:
markup = re.sub(
    r'<ac:structured-macro\b[^>]*ac:name="rollout-checklist"[^>]*>(.*?)</ac:structured-macro>',
    r'<p>[Rollout Checklist]</p>\1',
    markup,
    flags=re.S,
)
```

Adjust the macro name and the replacement to match what you actually found.
The pattern is always: **match the `ac:name` value, keep whatever text is
inside, discard the surrounding `ac:`-namespaced wrapper tags.**

After editing, re-run Step 2's command and re-check. No reinstall needed —
this repo runs from source, so the edit takes effect immediately.

### 3b. A table's columns are shuffled or a row is missing

Check the raw XHTML for nested tables or merged cells (`colspan`/`rowspan`).
The converter in `_html2md.py` handles plain tables only. If you see
`colspan=` or `rowspan=` in the raw output around that table, that is the
cause — this converter doesn't support merged cells. Either:
- ask whoever owns the template to simplify that table (best long-term fix),
  or
- treat that one table as a known gap and describe it in words instead when
  `/mr-write` fills that section.

### 3c. A checklist item's checked/unchecked state is wrong

This was a real bug once already (a lookahead reading the wrong item's
status) and was fixed — if you see it again, it's a **new** bug, not the old
one. Report the exact raw XHTML for one wrong `<ac:task>...</ac:task>` block
plus what the Markdown incorrectly showed. That's small, structural, and
perfectly safe to share for help — it's markup shape, not your team's actual
content.

### 3d. Still stuck

Everything above is exhausted. What's safe to ask for outside help with,
without exposing template content:
- **Safe to share:** the macro *name* (e.g. `rollout-checklist`), the general
  *shape* of the XHTML around it (tag nesting, attribute names — not the
  human-written text inside), the exact error message if any.
- **Not safe to share:** the actual filled-in text, section titles that reveal
  internal project/product names, anything your org would call confidential.

Genericize before asking: replace real words with placeholders (`ac:name="X"`,
`<p>[some sentence]</p>`) so the *structure* is visible but the *content*
isn't.

---

## Step 4 — Verify Jira

**Run:**
```
python -m donnyt.cli sprints --state active
python -m donnyt.cli velocity --sprints-back 3
```

**Expect:** the first prints your active sprint (name, dates, goal — goal may
be empty, that's fine). The second prints a `history` list with 1–3 entries,
each with `committed_points` and `completed_points`, plus an
`average_completed_points` at the end.

**If this fails:**
- Empty `sprints` output with no error — you're pointed at the right board but
  there's genuinely no active sprint right now. Not a bug.
- `error` mentioning `board_id` — `doctor` already validates this; re-run it,
  it lists the valid board ids for your project key.
- `average_completed_points: 0.0` with an empty `history` — there are no
  *closed* sprints yet on this board, or `jira.done_statuses` in
  `config.toml` doesn't match your workflow's actual status names
  (capitalization matters). Check a closed issue's status name in Jira and
  match it exactly.

**Also check `story_points_field`:**
```
python -m donnyt.cli jql "project = YOURKEY AND status = Done" --limit 3
```
Look at the `points` field in the output for each issue. If it's `null` for
issues you know had story points, `jira.story_points_field` in `config.toml`
is wrong for your site. Find the right one:
```
python -m donnyt.cli jql "key = YOURKEY-1234"
```
won't show custom field ids directly — instead open, in a browser,
`<your-site>/rest/api/3/issue/YOURKEY-1234?fields=*all` and search that page
for the number you expect to see; the field name right above it (something
like `customfield_10016`) is the value to put in `config.toml`.

---

## Step 5 — Verify GitLab

**Run:**
```
python -m donnyt.cli mrs --state opened --limit 5
```

**Expect:** a list (possibly empty, if nothing's currently open) with no
error.

**If this fails:** `doctor`'s `gitlab` line names the problem — usually
`gitlab.default_project` in `config.toml` not matching the exact
`group/subgroup/repo` path, or the token missing the `api` scope.

---

## Step 6 — Verify the vault

**Run:**
```
python -m donnyt.cli sync --sprints-back 2
python -m donnyt.cli vault-stats
```

**Expect:** `sync` reports sprints and merge requests written; `vault-stats`
shows non-zero counts under `by_type` — at least `sprint`, likely `person` and
`mr`.

Then, open `vault/` in Obsidian (**Open folder as vault**) and look at the
graph view (`Ctrl/Cmd+G`). You should see colored nodes — sprints in green,
people in blue — connected to each other. If it's all disconnected dots with
no lines between them, the sync ran but linking failed; report the exact
output of the `sync` command for help.

---

## Step 7 — Dry-run the MR skill against a real branch

Only do this once Steps 1–6 all pass.

Pick a real feature branch with a few commits — ideally one not yet opened as
an MR, so nothing gets created by accident.

In Claude Code, ask:

> Draft the MR description for branch `<branch-name>` in `<repo-path>`, using
> `/mr-write`. Show me the finished description but do NOT create the MR —
> stop before that step.

The skill is already written to stop and show you the description before
creating anything — this instruction is a belt-and-suspenders reminder, not a
workaround.

**Check the output against your template's actual sections one more time** —
same as Step 2, but now checking that the *filled-in* content (not just the
empty template) landed in the right places, pulled real commit/diff
information, and didn't invent anything (no fabricated ticket numbers,
no fabricated reviewer names).

Once that reads correctly, the setup is done. Everyday use from here is just
`/mr-write`, `/sprint-plan`, and `/vault-sync` — see `README.md`.

---

## Appendix — things this runbook deliberately does NOT ask you to do

- It never asks you to paste template content, issue content, or code into a
  chat with an external model. Every check is "run a command, look at two
  things next to each other on your own screen."
- It never asks you to create, publish, or move anything in Jira, GitLab, or
  Confluence before Step 7, and Step 7 explicitly stops short of creating
  anything.
- If a step's fix isn't covered above and isn't safely genericizable, stop and
  flag it to a human rather than guessing — a wrong guess here (e.g.
  mis-mapping which Jira field is story points) produces sprint plans sized on
  bad data, silently.
