---
name: sprint-plan
description: Plan the next sprint from Jira — velocity, capacity, backlog selection and a written plan. Use when the user says "plan the sprint", "sprint planning", "what goes in the next sprint", "capacity", "velocity", or is preparing for a planning session.
---

# Plan a sprint

Produce a plan the team can actually commit to: sized against what they have
historically *finished*, balanced per person, and written down where it can be
found again.

## Steps

### 1. Establish the baseline

Call these before proposing anything:

- `jira_velocity` — completed points per recent closed sprint, plus the mean.
  This is the number to size against. Committed points are not evidence.
- `jira_sprints` with `state: "active"` — what is still in flight.
- `jira_workload` on the active sprint — who is already loaded.

If velocity has fewer than three sampled sprints, say so. A mean over two
sprints is not a forecast, and the plan should be presented as a starting guess
rather than a commitment.

### 2. Account for spillover and availability

- Unfinished work in the active sprint carries over. Subtract it from available
  capacity before selecting anything new.
- Ask the user about leave, on-call, interviews and holidays for the coming
  sprint. These are not in Jira and they routinely cost 20–30% of capacity.
  Do not guess — ask, then adjust.

Team capacity comes from `[[team.members]]` in `config.toml`. If the roster is
empty or the capacities are all zero, say so and plan on velocity alone.

### 3. Select the work

Call `jira_backlog` for the ranked candidate pool, then propose a selection:

- Fill to the **velocity average**, not to total capacity. Capacity is the
  ceiling; velocity is the evidence.
- Respect rank order unless there is a stated reason to deviate — and state it.
- Flag unestimated issues. An issue with no points cannot be planned; either
  get an estimate or leave it out.
- Check dependencies: if A blocks B, either both go in or neither does.
- Balance per person against their configured capacity, not evenly. Watch for
  one person carrying every hard item.

### 4. Present it for review

Show the proposed sprint as a table — issue, summary, points, assignee — with:

- total points versus velocity average and versus capacity,
- per-person load,
- anything deliberately excluded, and why,
- the risks you can see (single points of failure, unestimated work,
  dependencies on other teams).

Then stop and let the user adjust. Do not create anything in Jira yet.

### 5. Apply it, once approved

Only after explicit approval:

- `jira_create_sprint` if the sprint does not exist, with a real goal — one
  sentence naming the outcome, not "finish the tickets".
- `jira_add_to_sprint` with the agreed issue keys.

These change shared team state. Confirm before each.

### 6. Write it down

- `vault_sync_sprint` — the sprint note in Obsidian, linked to every person in
  it.
- `confluence_publish` — if the team reads plans in Confluence. Ask first;
  publishing is visible to everyone.

Record the reasoning, not just the selection. In six weeks the useful part is
*why* something was cut.

## Running a retro instead

When asked to look back rather than forward:

1. `jira_sprint_issues` on the closed sprint.
2. Compare committed against completed — `jira_velocity` has both.
3. Identify what carried over and look for the pattern: consistently
   underestimated issue types, work blocked on other teams, interrupt load.
4. `vault_record_decision` for anything the team decides to change, so the
   decision is linked to the people who made it.
