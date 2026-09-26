---
name: prd-write
description: Write a product requirements document (PRD) from a problem statement and a proposed solution, following the team's Confluence PRD template. The PRD defines the user experience and comes before any tickets exist. Use when the user says "write a PRD", "spec this feature", "product requirements", "turn this idea into a PRD", or describes a problem and the solution they have in mind.
---

# Write a PRD from the Confluence template

A PRD is written **before** any tickets exist. It takes a problem and the
solution the user has in mind, and defines what that solution looks like to
the people who use it: flows, screens, states, and testable requirements.

When the PRD is approved, product and the team lead cut the tickets from it
themselves, and sprint planning schedules those tickets. So this skill never
creates Jira issues, epics or sprints. Its job ends at a published draft.

## Steps

### 1. Fetch the template first

Call `confluence_get_prd_template`. It returns the template as Markdown, its
section headings, and `parent_id`, the page PRDs are published under.

If it fails with `no_prd_template`, stop and report it; do not fall back to a
PRD shape from memory. The fix is `confluence.prd_template_page_id` in
`config.toml`, and `donnyt_doctor` confirms it.

### 2. Take in the problem and the solution

The user gives you two things, in any form (a few sentences, a file, notes
from a meeting, a Confluence page):

- **The problem**: who has it, what it costs them, how we know.
- **The solution**: what they want built, usually described from the
  user's side ("customers see their past orders and can download invoices").

Read everything they point you at: `confluence_get_page` or
`confluence_search` for pages, the file itself for files. Then check
`vault_search` for earlier decisions on the same topic, so the PRD does not
contradict something the team already settled. Cite the decision note when it
constrains the design.

### 3. Find the gaps and ask, once

Map what you have onto the template. A problem and a solution sketch usually
leave out success metrics and targets, non-goals, the different kinds of user,
what happens on the unhappy paths (empty, error, no permission), and
non-functional numbers.

Ask about the gaps in **one** grouped message, before drafting. Offer a
concrete suggestion for each so the user can answer "yes" instead of writing
it themselves, and label it as a suggestion. If they would rather you draft
first, do so and put every unanswered gap under **Open questions** with an
owner, or `owner: TBD`.

Never invent metrics, targets, dates, owners, customer quotes or research
findings. A PRD with a made-up number is worse than one with an honest open
question.

### 4. Draft every section

Work through the template's sections in order. Most of the effort goes into
**Proposed solution** and **User experience**; that is what this document is
for.

- Keep the template's exact headings, order, tables and checklists. Delete
  the guidance itself: italic placeholder hints and the template's own
  callouts (`[Info]`, `[Warning]`) are instructions to the author, not
  content. Do act on what they say.
- Where a section genuinely does not apply, write `N/A: <one-line reason>`.
  Never silently drop a section.
- **Proposed solution** is one or two paragraphs a new team member could
  follow. It describes what the user gets, not how it is built: no
  databases, endpoints or frameworks.
- **User flows**: one numbered list per flow, from where the user starts to
  the outcome they wanted. Include the main flow and every alternative the
  solution implies (first-time use, returning user, the admin side).
- **Screens**: one row per screen or view the flows touch: what it is for,
  what it shows, what the user can do there. A screen with no action is
  usually a sign it can be merged into another.
- **States and edge cases**: for each screen, what the user sees when it is
  empty, loading, failed, forbidden, or holding far more data than usual.
  These are the requirements that get forgotten, so be complete.
- **Mockups**: once the Screens table and states are settled, follow the
  `ui-mock` skill to draw each screen, and the key empty and error states, in
  the style of the team's system. Under **Mockups**, give each one a line
  and the image: `**Orders list**` then
  `![Orders list](attachment:orders-list.png)`. If mockups cannot be made
  (no browser, or the user declines), write `Pending: <reason>`. The screens
  are still fully described in words above.
- **Requirements** get stable ids (`R1`, `R2`, ...), one testable statement
  each from the user's side, a priority, and acceptance criteria in
  given / when / then form. Size each so it could become one ticket, and
  split any that hides an "and". Every flow step and every edge case should
  be covered by some requirement.
- **Priorities and status** are written `[Status: Must]`, `[Status: Should]`,
  `[Status: Could]`, `[Status: Won't]`, and document status `[Status: Draft]`.
  Publishing turns them back into Confluence status labels.
- **Non-functional requirements** need numbers: "results appear within 1 s
  for 95% of searches", not "fast".
- **Tickets** row stays as `To be created once approved.` Never invent an
  issue key.
- **Sign-off** checkboxes stay unticked. Only people tick them.
- Keep the template's appendix as a normal `## Appendix` heading with its
  content under it. The expand block does not survive publishing.

If the solution touches personal data, payments, authentication or data
deletion, say so under **Dependencies and risks** and flag the security
review.

### 5. Show it before publishing

Print the finished PRD, show the mockup PNGs, and ask for confirmation. Point out the open questions
and anything you assumed. Publishing is visible to the whole team, so confirm
first.

### 6. Publish

Write the Markdown to a file and call `confluence_publish` with the title
`PRD: <feature name>`, `parent_id` from step 1, and `attachments` listing
every mockup PNG *and* its HTML source. That gives each PRD its own page
under the PRDs parent, with the files on a child page
`PRD: <feature name> - Attachments`; the images still show inline in the
PRD, and the HTML sources are there to regenerate them. Never attach the
reference screenshots. Leave the status at
`[Status: Draft]`; the team moves it forward. If a page with that title
already exists it is updated in place, so check with the user before
overwriting a PRD someone else wrote.

### 7. Record it in the vault

Call `vault_write_note` with `kind: "project"`, the PRD title, a short summary
(the problem, the proposed solution, the Must requirements and the Confluence
URL), and `links_to` for any decision notes you cited. Once tickets exist, the
sprint and MR notes that deliver them can link back to it.

## Notes

- Do not create tickets, even when asked to "break it down". Offer the
  requirements table as the breakdown, and say that tickets are cut from it
  by product and the team lead.
- Requirements from a meeting or a 1:1 go into the PRD as requirements, never
  as who said what. Person notes are private and never feed a published page.
- A PRD with more than about 15 Must requirements is usually several
  features. Say so once and suggest a split. If the user wants one PRD, write
  one PRD.
- Rewriting an existing PRD: fetch it with `confluence_get_page`, keep its
  decisions and ids (`R3` stays `R3`), and list what changed in your message,
  not in the document.

## If the donnyt tools are not available

On a host where the `mcp` package could not be installed, the `donnyt_*`,
`jira_*`, `gitlab_*`, `confluence_*` and `vault_*` tools do not exist -- but
every one has an identical CLI command. Run `python -m donnyt.cli tools` for
the mapping, then use the commands through the shell (from the repo root, with
the repo's `.venv` Python). Same data, same rules: the confirm-before-publishing
steps above apply unchanged. Pass long Markdown (PRDs, notes) with
`--file <path>` rather than inline.
