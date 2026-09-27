---
name: sprint-plan
description: Turn the lead's sprint brief (vault/Sprints/<name>.md) into a Jira sprint — goals first, then availability, then people's focus — with or without story points. Use when the user says "plan the sprint", "sprint planning", "create the sprint from the brief", "what goes in the next sprint", "capacity", "velocity", or is preparing for a planning session.
---

# Plan a sprint from the brief

The lead writes a **sprint brief** before each sprint: a note in the vault's
`Sprints/` folder, from `_templates/Sprint.md`, holding the dates, the
**vectors** (the sprint's goals and their measures), who is away, who is on
call, and anything else that matters. People notes carry each person's
**Focus**. Your job is to turn the brief into a sprint the team can finish,
and, once the lead approves it, create it in Jira.

The team's process is still forming. Issues may have no story points. Some
may have points, and later all of them will. Follow what the brief and the
data say, and never impose a sizing method.

## Priorities, in this order

1. **Vectors decide what goes in.** The sprint exists to move its goals.
2. **Availability decides how much.**
3. **Focus decides who does it.** Focus matters, but it never pushes goal
   work out. When the two conflict, the goal wins and the lead decides. List
   every conflict.

## Steps

### 1. Read the brief

- Use the brief the user names. Otherwise look for a sprint note with
  `status: draft` (`vault_search` for `status: draft`). If there is none,
  say so and offer to copy the template to `Sprints/<sprint name>.md` for
  them to fill in. **Do not write the brief's content yourself.** The dates,
  goals and availability are the lead's to state.
- Call `vault_sprint_brief` with its title. Ask about everything in
  `missing` before going on. A brief without vectors can still be planned,
  but ask what the sprint is for first.
- If `jira_sprint` is set, a sprint of this name already exists. Plan into
  it and update it; don't create a second one.
- Anyone in `people` with `in_roster: false` or `jira_set: false` cannot be
  assigned. Say so, and point at `[[team.members]]` in `config.toml`.

### 2. Gather the rest

- `jira_sprints` with `state: "active"`, then `jira_sprint_issues` on it.
  Unfinished work may carry over, so ask whether it moves into this sprint.
- `jira_backlog`: the candidate pool, in rank order.
- `jira_velocity`: past throughput. `average_completed_issues` is always
  there. `average_completed_points` is there only once sprints were estimated
  (`estimated_sprints`). With fewer than three sprints behind either number,
  call it a rough guide, not a forecast.

### 3. Work out availability

For each person: `working_days` less their days off, less their on-call days
times `on_call_cost` (the brief's share of a day that on-call takes; 1 = the
whole day), less anything in their Notes ("50% interviews"). Present it as
available days out of `working_days`. When the brief is vague ("some days
off"), ask rather than guess. Holidays and freezes in Notes apply to everyone.

### 4. Propose

**What goes in, by vector:**

- `must_include` goes in first, whatever else happens. `keep_out` stays out.
- Then, for each vector in the brief's order, the backlog issues that move
  it, in rank order. Say which vector each issue serves.
- Work that serves no vector (bugs, maintenance) goes in only with room
  left, and is labelled as such.
- If A blocks B, both go in or neither does.

**How much:**

- Where issues have points and velocity has `average_completed_points`,
  size against it, scaled by the share of team days available. Size on
  completed points, never committed.
- Where they don't, size by issue count: `average_completed_issues`, scaled
  the same way. Say plainly that a count is a rough measure, since issues
  vary in size, and point out any issue that looks much larger than the rest.
- In a mix, show both: the points total of the estimated issues, and the
  count of the unestimated ones.
- **Unestimated issues are normal here.** List them and flag them; never
  drop an issue for having no points.

**Who does it:**

- Match issues to each person's `focus` and `role`, weighted by available
  days (points, or issue count, per available day).
- When goal work needs someone off their focus, because nobody on-focus
  has room or the work needs their skills, assign it anyway and add it to
  **Focus conflicts**.
- Watch for one person carrying every hard item, or every on-call week.

### 5. Present it and stop

Show:

- a table grouped by vector: issue, summary, points (or "—"), assignee;
- the load per person against their available days;
- **Focus conflicts**: the issue, the person, what their focus says, and why
  the goal needed them;
- what was left out and why, and the risks (unestimated work, dependencies
  on other teams, on-call overlap, freezes).

Then let the lead adjust. **Do not touch Jira yet.**

### 6. Apply it, once approved

These change what the team sees, so confirm before each one:

1. `jira_create_sprint` with the brief's title **exactly** as the name, the
   brief's `start` and `end`, and a goal: one sentence drawn from the
   vectors. If `jira_sprint` exists, use `jira_update_sprint` instead.
2. `jira_add_to_sprint` with the agreed keys.
3. `jira_assign`, one call per person.

### 7. Close the loop

Call `vault_sync_sprint` with the new `sprint_id` and `plan`: the Markdown
reasoning. Include the issues per vector, how the sprint was sized, the
focus conflicts and how each was settled, and what was cut and why. The
Jira facts and the plan are added below the brief in the same file. Its
`status` becomes `planned`, and the lead's text is untouched.

`confluence_publish` only if the lead asks. Never include anyone's Focus, or
anything from a person note, in what gets published.

## Running a retro instead

When asked to look back rather than forward:

1. `vault_sync_sprint` on the closed sprint, then `vault_read` its note: the
   brief, its vectors, the plan, and **Done by** -- what each person finished,
   merged and reviewed.
2. `jira_velocity` for committed against completed.
3. For each vector, did its measure move? Say what the record shows. If
   it cannot tell, say that too.
4. Look at what carried over for the pattern: underestimated work, work
   blocked on other teams, interrupt load, availability that was lower than
   planned.
5. Open the retro with **Done by**: it is the sprint's record of each
   person's work, meant to be shown. Credit what the record shows, and
   nothing about anyone's performance beyond it.
6. `vault_record_decision` for anything the team decides to change, including
   changes to how it plans. The process is still forming, and those
   decisions are part of its history.

## If the donnyt tools are not available

On a host where the `mcp` package could not be installed, the `donnyt_*`,
`jira_*`, `gitlab_*`, `confluence_*` and `vault_*` tools do not exist -- but
every one has an identical CLI command. Run `python -m donnyt.cli tools` for
the mapping, then use the commands through the shell (from the repo root, with
the repo's `.venv` Python). Same data, same rules: the confirm-before-sending
steps above apply unchanged. Pass long Markdown (notes, pages) with
`--file <path>` rather than inline; the sprint plan goes to
`sync-sprint --plan-file <path>`.
