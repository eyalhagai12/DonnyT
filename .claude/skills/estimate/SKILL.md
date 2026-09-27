---
name: estimate
description: Estimate Jira issues from what similar past work really changed, across every GitLab repo the team works in — a size (XS–XL, mapped to story points) with reasoning, written to Jira after the lead approves. Use when the user says "estimate", "size these", "size the backlog", "how big is TEAM-123", "story points for", or before sprint planning when candidate issues are unestimated.
---

# Estimate issues from evidence

An estimate is a judgement, but it should rest on evidence: how big similar
work turned out to be, in the repos this work will touch. This skill gathers
that evidence, proposes a size per issue with its reasoning, and — only after
the lead approves — writes it to Jira.

The team's repos come from `[[gitlab.repos]]` in `config.toml`. Each repo
lists the Jira components or labels whose tickets touch it, so an issue's
components and labels decide which repos matter.

## Steps

### 1. Pick the issues

What the user names: issue keys, "the backlog" (`jira_backlog`), or a
sprint's issues (`jira_sprint_issues`). Skip issues that already have points
unless asked to re-estimate; say which were skipped.

### 2. Gather the evidence

Call `estimation_context` with the keys. For each issue it returns:

- the issue, with description, components and labels;
- `repos` it maps to — and `unmapped: true` when no component or label
  matches. **Ask the lead which repos** for those; don't guess. (The lasting
  fix is a component on the issue, or the component in `[[gitlab.repos]]`.)
- `similar`: finished issues most like it, each with what it actually
  changed per repo — files, lines added and removed, areas — and its points
  if it was estimated;
- `layout` of each mapped repo, to see which areas the work lands in;
- `sizes`: the scale, e.g. XS=1 S=2 M=3 L=5 XL=8.

If `gitlab_error` is set, the history could not be read — say so, and
estimate with low confidence.

### 3. Size each issue

Compare, don't guess:

- **Anchor on the similar issues.** "Like TEAM-12 (one package, ~100 lines
  with tests)" is a reason; "feels medium" is not. Similar issues that were
  estimated give a direct anchor; unestimated ones still show real size.
- **Read the description for scope** the summary hides: a data-model change,
  a new endpoint, validation, migrations, a new dependency.
- **Crossing repos costs more.** Work in two repos is two changes, two
  reviews, and a contract between them — size up.
- **Unknowns size up**, and say what they are.
- **Confidence**: high when several close matches agree; medium with loose
  matches; low with none (`similar` empty) — say "no comparable work".

Never invent history: cite only issues and numbers from `estimation_context`.

### 4. Present and stop

A table: issue, summary, **size (points)**, confidence, repos, and a one-line
reason citing the similar issues. Then list anything unmapped or low
confidence the lead should look at. **Do not write to Jira yet** — the lead
adjusts sizes first.

### 5. Write the agreed estimates

After approval, call `jira_set_estimate` for each issue with its size and a
reasoning of one or two sentences: the similar issues, the repos, and any
unknowns. It sets the points through the board and adds the reasoning as a
comment. Team-visible — confirm the batch once, then write them all.

### 6. Close the loop

Estimates get better by being checked. Once estimated work finishes,
`jira_velocity` starts reporting a points average, and the sprint retro can
compare estimate with outcome — an M that took two MRs and 400 lines was an L.
Say so when it happens; that is how the scale gets calibrated.

## If the donnyt tools are not available

Every tool has a CLI command (`python -m donnyt.cli tools`):
`estimate-context KEY [KEY ...]` and `set-estimate KEY SIZE --reasoning TEXT`.
Same rules: propose first, write only after approval.
