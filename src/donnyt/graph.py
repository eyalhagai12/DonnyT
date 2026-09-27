"""Build the knowledge graph: turn Jira and GitLab facts into linked notes.

Each builder writes one note and, crucially, the edges around it -- a sprint
note links every person who carried work in it, and records what each of them
finished, merged and reviewed. That reciprocity is what makes Obsidian's graph
view show the team rather than a pile of files.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from .config import WEEKDAYS, Config, load_config
from .gitlab import GitLabClient, MergeRequest
from .jira import Issue, JiraClient, Sprint
from .vault import Vault, bullets, link, parse_table, section, sections, slug, unlink

# A Jira key in free text, e.g. TEAM-1234.
ISSUE_KEY = re.compile(r"\b([A-Z][A-Z0-9_]+-\d+)\b")


def _size(issues: list[Issue]) -> str:
    """"9 issues (4 unestimated) · 12 pts where estimated" -- counts first,
    because a team that does not estimate still finishes issues."""
    unestimated = sum(1 for i in issues if i.points is None)
    text = f"{len(issues)} issue{'s' if len(issues) != 1 else ''}"
    if not issues:
        return text
    if unestimated == len(issues):
        return f"{text}, none estimated"
    points = round(sum(i.points or 0 for i in issues), 1)
    if unestimated:
        return f"{text} ({unestimated} unestimated) · {points} pts where estimated"
    return f"{text} · {points} pts"


# Sprint note lifecycle. A brief starts as `draft`; syncing it from Jira
# records how far it has got.
_STATUS = {"future": "planned", "active": "active", "closed": "closed"}

# Brief sections the reader understands. Anything else is passed on as text.
_BRIEF_SECTIONS = ("vectors", "availability", "on call", "room", "must include", "keep out", "notes")


def _mr_ref(mr: MergeRequest) -> str:
    """``team/todo!5``: MR numbers repeat across repos, so the repo is part of the name."""
    return f"{mr.project}!{mr.iid}" if mr.project else f"!{mr.iid}"


def working_days(start: str, end: str, weekend: list[str]) -> int | None:
    """Working days from ``start`` to ``end`` inclusive, or None if the dates don't parse."""
    try:
        first, last = date.fromisoformat(str(start)[:10]), date.fromisoformat(str(end)[:10])
    except ValueError:
        return None
    off = {WEEKDAYS.index(d) for d in weekend}
    return sum(
        1 for n in range(max((last - first).days + 1, 0))
        if (first + timedelta(n)).weekday() not in off
    )


def _issue_table(issues: list[Issue]) -> str:
    if not issues:
        return "_No issues._"
    rows = ["| Issue | Summary | Type | Points | Assignee | Status |", "| --- | --- | --- | --- | --- | --- |"]
    for issue in issues:
        assignee = link(issue.assignee) if issue.assignee else "—"
        points = issue.points if issue.points is not None else "—"
        summary = issue.summary.replace("|", "\\|")[:80]
        rows.append(
            f"| [{issue.key}]({issue.url}) | {summary} | {issue.issue_type} "
            f"| {points} | {assignee} | {issue.status} |"
        )
    return "\n".join(rows)


class GraphBuilder:
    def __init__(self, config: Config | None = None) -> None:
        self.config = config or load_config()
        self.vault = Vault(config=self.config)

    # -- sprints -----------------------------------------------------------
    def sync_sprint(
        self,
        sprint: Sprint,
        issues: list[Issue],
        workload: dict[str, Any],
        done: list[Issue],
        plan: str = "",
        merged: list[tuple[MergeRequest, list[str]]] | None = None,
    ) -> str:
        """Write the note for one sprint and touch every person it involved.

        The note is ``Sprints/<sprint name>.md`` -- so when a sprint brief of
        that name exists, the Jira facts land below it and the brief itself,
        being outside the managed blocks, is kept. ``plan`` is the planning
        reasoning; it is written only when given, and a later sync without it
        leaves the last one in place. ``merged`` is the sprint's merged MRs with
        their approvers, from :meth:`merged_work`; with it, the note gets a
        "Done by" section: what each person finished, merged and reviewed.

        ``done`` comes from ``JiraClient.done_in``: today's status alone would
        count spill-over as finished in every sprint it passed through.
        """
        title = sprint.name
        people = sorted({i.assignee for i in issues if i.assignee})

        overview = "\n".join(
            [
                f"- **State** — {sprint.state}",
                f"- **Dates** — {sprint.start or '?'} → {sprint.end or '?'}",
                f"- **Goal** — {sprint.goal or '_not set_'}",
                f"- **Committed** — {_size(issues)}",
                f"- **Completed** — {_size(done)}",
                f"- **Team** — {', '.join(link(p) for p in people) or '—'}",
            ]
        )

        load_rows = [
            "| Person | Issues | Unestimated | Points | Capacity | Over by |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for entry in workload.get("by_assignee", []):
            who = entry["assignee"]
            name = link(who) if who != "Unassigned" else "Unassigned"
            over = entry.get("over_by")
            load_rows.append(
                f"| {name} | {entry.get('issues', 0)} | {entry.get('unestimated', 0)} "
                f"| {round(entry['points'], 1)} | {entry.get('capacity') or '—'} "
                f"| {'+' if over and over > 0 else ''}{over if over is not None else '—'} |"
            )

        blocks = {
            "overview": f"## Overview\n\n{overview}",
            "workload": "## Workload\n\n" + "\n".join(load_rows),
            "issues": f"## Issues\n\n{_issue_table(issues)}",
        }
        if plan.strip():
            blocks["plan"] = f"## Plan\n\n{plan.strip()}"
        blocks["done-by"] = "## Done by\n\n" + self._done_by(done, merged)

        self.vault.upsert(
            title=title,
            kind="sprint",
            frontmatter={
                "type": "sprint",
                "status": _STATUS.get(sprint.state, sprint.state),
                "sprint_id": sprint.id,
                "state": sprint.state,
                "start": sprint.start,
                "end": sprint.end,
                "board": self.config.jira_board_id,
                "committed_issues": len(issues),
                "completed_issues": len(done),
                "unestimated_issues": sum(1 for i in issues if i.points is None),
                "committed_points": round(sum(i.points or 0 for i in issues), 1),
                "completed_points": round(sum(i.points or 0 for i in done), 1),
                "people": [f"[[{slug(p)}]]" for p in people],
                "tags": ["sprint"],
            },
            intro=f"_{sprint.goal}_\n" if sprint.goal else "",
            blocks=blocks,
        )

        for person in people:
            self._touch_person(person, sprint_title=title)

        return title

    def _person(self, handle: str) -> str:
        """A roster name for a Jira name or GitLab username, so one person is one note."""
        member = self.config.member_by(handle)
        return member.name if member else handle

    def _done_by(self, done: list[Issue], merged: list[tuple[MergeRequest, list[str]]] | None) -> str:
        """What each person finished, merged and reviewed -- the record to show them.

        Finished issues come from Jira (the assignee), merged and reviewed work
        from GitLab (the author, and every approver who is not the author).
        """
        work: dict[str, list[str]] = {}
        for issue in done:
            if issue.assignee:
                work.setdefault(self._person(issue.assignee), []).append(
                    f"Finished [{issue.key}]({issue.url}) {issue.summary}")
        for mr, approvers in merged or []:
            author = self._person(mr.author)
            work.setdefault(author, []).append(f"Merged [{_mr_ref(mr)}]({mr.url}) {mr.title}")
            for login in approvers:
                reviewer = self._person(login)
                if reviewer != author:
                    work.setdefault(reviewer, []).append(
                        f"Reviewed [{_mr_ref(mr)}]({mr.url}) {mr.title} — for {author}")
        if not work:
            return "_Nothing finished yet._"

        roster = [m.name for m in self.config.members]
        order = sorted(work, key=lambda n: (roster.index(n) if n in roster else len(roster), n))
        rank = {"Finished": 0, "Merged": 1, "Reviewed": 2}
        sections = []
        for name in order:
            lines = "\n".join(
                f"- {line}" for line in sorted(work[name], key=lambda line: rank[line.split()[0]])
            )
            sections.append(f"### {link(name)}\n\n{lines}")
        note = "" if merged is not None else "\n\n_GitLab was not read, so merged and reviewed work is missing._"
        return "\n\n".join(sections) + note

    def merged_work(self, sprint: Sprint) -> list[tuple[MergeRequest, list[str]]] | None:
        """MRs merged during the sprint in every configured repo, each with its
        approvers, oldest first. None when GitLab is not configured or not
        reachable: the sprint note is still worth writing without it."""
        if not (self.config.repos and sprint.start):
            return None
        try:
            gitlab = GitLabClient(self.config)
            merged = [
                (mr, gitlab.approvers(mr.iid, repo.project))
                for repo in self.config.repos
                for mr in gitlab.merged_between(sprint.start, sprint.end or "9999-12-31", repo.project)
            ]
            return sorted(merged, key=lambda pair: pair[0].merged_at)
        except Exception:
            return None

    def sprint_brief(self, title: str, jira: JiraClient | None = None) -> dict[str, Any]:
        """Read a hand-written sprint brief into what planning needs.

        Structured where the brief follows the template (dates, tables, bullet
        lists), raw text everywhere else, so a section the template does not
        know still reaches the planner. Adds each person's role and Focus from
        their note -- private context for assignments, never for publishing.
        Raises LookupError when there is no such note in Sprints/.
        """
        note = self.vault.read(title)
        if not note or note.path.parent != self.vault.note_path(title, "sprint").parent:
            raise LookupError(title)
        body = note.body
        start = str(note.frontmatter.get("start") or "")
        end = str(note.frontmatter.get("end") or "")
        weekend = self.config.weekend

        def listed(name: str) -> list[str]:
            return [unlink(b) for b in bullets(section(body, name))]

        def keys(name: str) -> list[str]:
            return sorted({key for item in listed(name) for key in ISSUE_KEY.findall(item)})

        def table(name: str) -> list[dict[str, str]] | str:
            """Rows when the section holds a table (none if unfilled), its text when not."""
            text = section(body, name)
            return parse_table(text) if re.search(r"^\s*\|", text, re.M) else text

        availability, on_call = table("availability"), table("on call")
        rows = [r for t in (availability, on_call) if isinstance(t, list) for r in t]

        # The roster first, then anyone the brief names who is not on it --
        # the planner should see them, and see that they cannot be assigned.
        roster = [m.name for m in self.config.members]
        named = {row.get("Person", "") for row in rows} - {""}
        people = []
        for name in roster + sorted(named - set(roster)):
            member = self.config.member_by(name)
            person = self.vault.read(name)
            focus = section(person.body, "focus") if person else ""
            focus = focus if re.sub(r"[-*+\s]", "", focus) else ""  # an unfilled "-" is no focus
            people.append(
                {
                    "name": name,
                    "in_roster": member is not None,
                    "jira_set": bool(member and member.jira),
                    "capacity": member.capacity if member else None,
                    "has_note": person is not None,
                    "role": str(person.frontmatter.get("role") or "") if person else "",
                    "focus": focus,
                }
            )

        existing, jira_error = None, ""
        try:
            client = jira or JiraClient(self.config)
            existing = next(
                (s.as_dict() for s in client.sprints() if s.name == note.title and s.state != "closed"),
                None,
            )
        except Exception as exc:  # the brief is still worth reading without Jira
            jira_error = f"{type(exc).__name__}: {exc}"

        missing = [name for name, value in (("start", start), ("end", end)) if not value]
        if not listed("vectors"):
            missing.append("vectors")
        # What a day on call costs, as a share of a working day (1 = the whole day).
        cost = note.frontmatter.get("on_call_cost")
        on_call_cost = float(cost) if isinstance(cost, (int, float)) else None
        if on_call and on_call_cost is None:
            missing.append("on_call_cost")

        result: dict[str, Any] = {
            "title": note.title,
            "path": str(note.path),
            "status": note.frontmatter.get("status", "draft"),
            "start": start,
            "end": end,
            "weekend": weekend,
            "working_days": working_days(start, end, weekend) if start and end else None,
            "vectors": listed("vectors"),
            "availability": availability,
            "on_call": on_call,
            "on_call_cost": on_call_cost,
            "must_include": keys("must include"),
            "keep_out": keys("keep out"),
            # What spare room goes to; empty means the default (next backlog items
            # that fit each person's Focus).
            "room": listed("room"),
            "notes": section(body, "notes"),
            "other_sections": {
                k: v for k, v in sections(body).items() if k.lower() not in _BRIEF_SECTIONS and v
            },
            "people": people,
            "jira_sprint": existing,
            "missing": missing,
        }
        if jira_error:
            result["jira_error"] = jira_error
        return result

    # -- decisions ---------------------------------------------------------
    def record_decision(
        self,
        title: str,
        context: str,
        decision: str,
        consequences: str = "",
        people: list[str] | None = None,
        related: list[str] | None = None,
    ) -> str:
        """An ADR-shaped note -- the thing you actually want to find six months on."""
        involved = people or []
        body = [
            f"## Context\n\n{context}",
            f"## Decision\n\n{decision}",
        ]
        if consequences:
            body.append(f"## Consequences\n\n{consequences}")
        if involved:
            body.append("## People\n\n" + "\n".join(f"- {link(p)}" for p in involved))
        if related:
            body.append("## Related\n\n" + "\n".join(f"- {link(r)}" for r in related))

        self.vault.upsert(
            title=title,
            kind="decision",
            frontmatter={
                "type": "decision",
                "date": date.today().isoformat(),
                "people": [f"[[{slug(p)}]]" for p in involved],
                "tags": ["decision"],
            },
            blocks={"decision": "\n\n".join(body)},
        )
        for person in involved:
            self._touch_person(person, decision_title=title)
        return title

    # -- people ------------------------------------------------------------
    def _touch_person(
        self,
        name: str,
        sprint_title: str = "",
        decision_title: str = "",
    ) -> None:
        """Ensure a person note exists. Their history comes from backlinks, so
        nothing needs appending -- Obsidian derives it."""
        member = self.config.member_by(name)
        frontmatter: dict[str, Any] = {"type": "person", "tags": ["person"]}
        if member:
            frontmatter.update({"jira": member.jira, "gitlab": member.gitlab})
            if member.capacity:
                frontmatter["capacity"] = member.capacity

        existing = self.vault.read(name)
        intro = "" if existing else (
            "One-on-ones, growth notes and context live here. "
            "Sprints and decisions link back automatically — "
            "check the backlinks pane for their history.\n\n"
            "## Focus\n\n"
            "%% What you want them working on and steered toward. Sprint "
            "planning reads this section. %%\n\n- \n"
        )

        self.vault.upsert(
            title=name,
            kind="person",
            frontmatter=frontmatter,
            intro=intro,
            blocks={} if existing else {"notes": "## Notes\n\n- "},
        )

    # -- full refresh ------------------------------------------------------
    def sync_all(self, sprints_back: int = 3) -> dict[str, Any]:
        """Pull the active sprint and recent closed ones into the vault in one pass."""
        jira = JiraClient(self.config)
        written: dict[str, list[str]] = {"sprints": [], "people": []}

        candidates = []
        active = jira.active_sprint()
        if active:
            candidates.append(active)
        closed = sorted(
            jira.sprints(state="closed"), key=lambda s: (s.end or "", s.id), reverse=True
        )
        candidates.extend(closed[:sprints_back])

        for sprint in candidates:
            issues = jira.sprint_issues(sprint.id)
            written["sprints"].append(
                self.sync_sprint(
                    sprint, issues, jira.workload(sprint.id), jira.done_in(sprint),
                    merged=self.merged_work(sprint),
                )
            )

        written["people"] = [n.title for n in self.vault.notes("person")]
        return {"written": written, "stats": self.vault.stats()}
