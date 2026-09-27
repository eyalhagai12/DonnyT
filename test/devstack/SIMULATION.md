# Simulating a sprint

The devstack holds a team of six building a todo API (see `todo/README.md`).
You are the lead and use DonnyT. Claude plays everyone else with `team.py`,
writing **real Go code** per ticket — so the repo keeps an honest record of
what each ticket changed, which is what complexity estimation will read.

All commands run from the repo root with the repo's Python, and with the
devstack as DonnyT's home:

```bash
export DONNYT_HOME=test/devstack/donnyt         # PowerShell: $env:DONNYT_HOME = "test\devstack\donnyt"
python test/devstack/seed.py                    # start from a clean world, if you want one
```

## The team

| Login | Name | Role | Notes |
| --- | --- | --- | --- |
| `maya` | Maya Cohen | Backend lead | owns the store; reviews data-model changes |
| `dan` | Dan Levi | Platform | runtime, config, `cmd/` |
| `noa` | Noa Katz | API features | endpoints and query parameters |
| `omer` | Omer Shapiro | Reliability and security | validation, auth; mentors Lior |
| `lior` | Lior Ben-David | Junior | middleware and tests; pairs with Omer |
| `tamar` | Tamar Adler | Part-time (50%) | docs and tests |

Their Focus lives in `donnyt/vault/People/`. Edit it like the real thing.

## 1. Plan — you, with DonnyT

1. Optional: `/prd-write` a feature. Cut its tickets with
   `python test/devstack/team.py new-issue "..." --description "..."`.
2. Write the brief: copy `donnyt/vault/_templates/Sprint.md` to
   `donnyt/vault/Sprints/TEAM Sprint 4.md` and fill it in — dates, vectors,
   who is away, who is on call.
3. `/sprint-plan`. Review the proposal, adjust, approve; it creates the
   sprint in Jira and writes the plan below your brief.
4. `python test/devstack/team.py start-sprint <id>`.

## 2. Run it — Claude as the team

Reset the working copy first: `python test/devstack/team.py clone`
(`donnyt/work/todo`, git-ignored).

For each ticket, as its assignee:

```bash
git -C test/devstack/donnyt/work/todo checkout -b TEAM-11-list-order main
#   ...write the change and its tests, in the style of the code around it...
go -C test/devstack/donnyt/work/todo test ./...
python test/devstack/team.py move TEAM-11 "In Progress"
python test/devstack/team.py commit --as maya -m "TEAM-11 Return todos oldest first"
python test/devstack/team.py push --as maya TEAM-11-list-order
#   a short description of what changed and why, written as the engineer would
python test/devstack/team.py mr --as maya TEAM-11-list-order --title "TEAM-11 Return todos oldest first" --file desc.md
python test/devstack/team.py review --as omer <iid> --note "..." --approve
python test/devstack/team.py merge --as omer <iid>
python test/devstack/team.py move TEAM-11 Done
git -C test/devstack/donnyt/work/todo checkout main && python test/devstack/team.py clone
```

Rules that keep the simulation honest:

- **Real code, real tests.** `go vet` and `go test` pass before every push.
  Nothing is stubbed.
- **One ticket, one branch, one MR**, named `TEAM-N-…`. Commits by the
  assignee; review (with `--approve`) and merge by someone else — Maya for the
  store, Omer for anything security-shaped. Approvals are what credit a
  reviewer in the sprint's **Done by**.
- **Stay in character.** A junior's first MR can get review comments and a
  second commit. Tamar works half-time. Someone the brief says is away does
  nothing on those days.
- **Let reality happen.** Leave a ticket unfinished if the sprint would not
  have finished it; take an interrupt bug mid-sprint. Spill-over is data.
- DonnyT never writes to GitLab; the engineers do, through `team.py`.

## 3. Close — you, with DonnyT

1. `python test/devstack/team.py close-sprint <id> --to <next id>` —
   unfinished work moves on, remembering it spilled over (omit `--to` to send
   it to the backlog).
2. `vault_sync_sprint` for the closed sprint, then `/sprint-plan` in retro
   mode: did the vectors' measures move?
3. Write the next brief. Repeat.

## Starting over

`python test/devstack/seed.py` puts GitLab, Jira and the vault back to v0.
Everything written during simulated sprints is lost — that is the point of it.
