---
type: topic
tags:
  - index
---

# Home

The team knowledge graph. Sprints, merge requests, decisions and people, linked
so that last quarter stays answerable.

## Start here

- **Graph view** (`Ctrl/Cmd+G`) — the whole team as a picture. Nodes are
  coloured by type: people blue, sprints green, MRs orange, decisions purple.
- **A person's history** — open their note and read the **backlinks** pane.
  Every sprint, MR and decision that named them shows up there automatically.
- **Why something happened** — search `Decisions/`.

## Folders

| Folder       | What lives here                                  |
| ------------ | ------------------------------------------------ |
| `People/`    | One note per team member. Focus, 1:1s, growth, context. |
| `Sprints/`   | One per sprint. Write the brief from `_templates/Sprint.md`; the rest is added from Jira. |
| `MRs/`       | Merge requests worth remembering.                |
| `Projects/`  | Longer arcs that span sprints.                   |
| `Decisions/` | Context, decision, consequences.                 |
| `Meetings/`  | Retros, planning, skip-levels.                   |
| `Topics/`    | Everything else worth linking.                   |

## How notes stay fresh

Generated content sits between markers:

```
<!-- donnyt:begin overview -->
...regenerated on every sync...
<!-- donnyt:end overview -->
```

**Anything you write outside those markers is yours and is never overwritten.**
So 1:1 notes on a person's page survive every sync. Don't edit inside a marked
block — write above or below it.

Refresh from Jira and GitLab with `/vault-sync`, or from a terminal:

```
python -m donnyt.cli sync
```
