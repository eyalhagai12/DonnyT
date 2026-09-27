Notes of this type live here. See Home.md.

## Planning a sprint

1. Copy `_templates/Sprint.md` to `Sprints/<sprint name>.md`. The file name
   becomes the Jira sprint name, so name it the way the board does
   (`Sprint 7`).
2. Fill it in: dates, vectors (the goals, most important first), who is away,
   who is on call, what must go in or stay out.
3. Ask Claude to plan the sprint from it (`/sprint-plan`). It proposes the
   sprint and creates it in Jira once you approve.

After that, the same file is the sprint's note. The overview, workload,
issues and plan are added below your brief, and each sync refreshes them.
Your brief is never overwritten.
