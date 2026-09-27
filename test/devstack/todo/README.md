# todo — the devstack's reference product

A small todo API in Go, standard library only. The simulated team builds it
on the devstack's GitLab (`team/todo`), and DonnyT is tested against it.

Only **v0** lives here, as a patch series: one patch per Jira ticket, each
authored by the person who did it and dated inside its sprint.

| Patch | Ticket | By | Sprint |
| --- | --- | --- | --- |
| 0001 | TEAM-1 Project skeleton and health check | Dan | 1 |
| 0002 | TEAM-2 Todo model and in-memory store | Maya | 1 |
| 0003 | TEAM-3 Create and list todos | Noa | 1 |
| 0004 | TEAM-5 Validate input and return JSON errors | Omer | 2 |
| 0005 | TEAM-6 Request logging middleware | Lior | 2 |
| 0006 | TEAM-7 Handler tests | Tamar | 2 |
| 0007 | TEAM-4 Get, update and delete a todo | Noa | 3 (spilled over from 2) |
| 0008 | TEAM-8 Graceful shutdown and config from env | Dan | 3 |
| 0009 | TEAM-9 Mark a todo done or undone | Maya | 3 |
| 0010 | TEAM-10 README with API examples | Tamar | 3 |

`seed.py` replays them into GitLab's `main` with `git am`, so every commit
builds and passes its tests. Everything after v0 is written during simulated
sprints and lives only in GitLab — see `../SIMULATION.md`.

v0 has two real bugs, on purpose. They are backlog tickets TEAM-11 and
TEAM-12:

- `GET /todos` iterates a map, so the order changes between calls;
- `PATCH` sets the title unconditionally, so `{"done": true}` blanks it.

To read v0 as a tree:

```bash
git init /tmp/todo && cd /tmp/todo && git am path/to/test/devstack/todo/patches/*.patch
```

To change v0, change the history the same way: rebuild the commits in a
scratch repo, then `git format-patch --root --no-signature --zero-commit -o patches`
and re-run `seed.py gitlab`.
