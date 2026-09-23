---
name: vault-sync
description: Maintain and query the Obsidian knowledge graph of the team — sprints, merge requests, people, decisions. Use when the user asks about team history, wants notes updated or synced, asks "what has X been working on", "when did we decide Y", "prep for a 1:1", or mentions the vault, Obsidian or the knowledge graph.
---

# The team knowledge graph

The vault is the memory. Jira and GitLab know what happened *this* sprint; the
vault is what makes last quarter answerable. Keep it accurate, keep it
readable, and never trample what the user wrote themselves.

## The one rule that matters

Everything this toolkit writes lives between markers:

```
<!-- donnyt:begin overview -->
...generated...
<!-- donnyt:end overview -->
```

Regenerating replaces only those blocks. **Prose outside them is the user's and
must survive.** That is why 1:1 notes on a person page are safe even though the
page is refreshed every sync.

Never hand-edit inside a managed block — it will be overwritten on the next
sync. Write outside it instead.

## Structure

| Folder | Type | What it holds |
| --- | --- | --- |
| `People/` | `person` | One per team member. 1:1s, growth, context. |
| `Sprints/` | `sprint` | One per sprint: goal, workload, issues. |
| `MRs/` | `mr` | Notable merge requests and why they mattered. |
| `Projects/` | `epic` | Longer arcs spanning sprints. |
| `Decisions/` | `decision` | ADR-shaped: context, decision, consequences. |
| `Meetings/` | `meeting` | Retros, planning, skip-levels. |
| `Topics/` | `topic` | Anything else worth linking. |

Edges are `[[wikilinks]]`. A person's history is their **backlinks** — nothing
needs appending to their page for it to accumulate.

## Keeping it current

- `vault_sync` — recent sprints and open MRs in one pass. Run it before
  answering any question about team history, so the answer is not stale.
- `vault_sync_sprint` — one sprint.
- `vault_sync_mr` — one merge request, linked to its Jira issue and author.

Sync is safe to re-run.

## Answering questions

Reach for the graph, not a full-text scan, when the question is relational:

- *"What has Maya been working on?"* → `vault_links` on her note. Backlinks are
  the answer: every sprint, MR and decision that named her.
- *"When did we decide to drop the v1 API?"* → `vault_search` for the topic,
  then `vault_read` the decision note.
- *"What happened in Sprint 14?"* → `vault_read` that sprint note.

Say plainly when the vault has nothing on something, rather than reconstructing
a plausible history. An empty graph is a fact about the graph.

## Writing to it

- `vault_record_decision` — for anything the team decided. Capture the
  **context** properly: the constraints at the time are what make it useful
  later, and they are exactly what nobody remembers.
- `vault_write_note` — meetings, topics, project pages. Pass `links_to` so the
  note joins the graph instead of floating loose.

Write notes a person would want to read: lead with the substance, keep tables
for data, and link generously — an unlinked note is invisible in the graph.

## Preparing a 1:1

1. `vault_links` on the person — recent sprints, MRs, decisions.
2. `jira_search` for their open issues.
3. `vault_read` their note for what was discussed last time and anything
   outstanding.
4. Summarise: what they shipped, what is in flight, what is stuck, what was
   promised last time.

Keep the output private to the user. These notes are about a real person —
report what the record shows, do not editorialise about their performance, and
do not publish any of it to Confluence or GitLab.
