"""Build the knowledge graph: turn Jira and GitLab facts into linked notes.

Each builder writes one note and, crucially, the edges around it -- a sprint
note links every person who carried work in it, a merge request note links its
author and its Jira issue. That reciprocity is what makes Obsidian's graph view
show the team rather than a pile of files.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from .config import WEEKDAYS, Config, load_config
from .gitlab import GitLabClient, MergeRequest
from .jira import Issue, JiraClient, Sprint
from .vault import Vault, bullets, link, parse_table, section, sections, slug, unlink

# A Jira key embedded in a branch name or MR title, e.g. TEAM-1234.
ISSUE_KEY = re.compile(r"\b([A-Z][A-Z0-9_]+-\d+)\b")


def extract_issue_key(*texts: str) -> str:
    for text in texts:
        match = ISSUE_KEY.search(text or "")
        if match:
            return match.group(1)
    return ""


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
_BRIEF_SECTIONS = ("vectors", "availability", "on call", "must include", "keep out", "notes")


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
    ) -> str:
        """Write the note for one sprint and touch every person it involved.

        The note is ``Sprints/<sprint name>.md`` -- so when a sprint brief of
        that name exists, the Jira facts land below it and the brief itself,
        being outside the managed blocks, is kept. ``plan`` is the planning
        reasoning; it is written only when given, and a later sync without it
        leaves the last one in place.

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
            "must_include": keys("must include"),
            "keep_out": keys("keep out"),
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

    # -- merge requests ----------------------------------------------------
    def sync_merge_request(
        self,
        mr: MergeRequest,
        project: str,
        issue: Issue | None = None,
        sprint_name: str = "",
        summary: str = "",
    ) -> str:
        title = f"MR {mr.iid} — {mr.title.removeprefix('Draft:').strip()}"[:120]

        facts = [
            f"- **Project** — [{project}]({self.config.gitlab_url}/{project})",
            f"- **Branch** — `{mr.source_branch}` → `{mr.target_branch}`",
            f"- **State** — {'draft' if mr.draft else mr.state}",
            f"- **Author** — {link(mr.author) if mr.author else '—'}",
            f"- **Link** — [{mr.url}]({mr.url})",
        ]
        if issue:
            facts.append(f"- **Issue** — [{issue.key}]({issue.url}) · {issue.summary}")
        if sprint_name:
            facts.append(f"- **Sprint** — {link(sprint_name)}")

        frontmatter = {
            "type": "mr",
            "mr_iid": mr.iid,
            "project": project,
            "state": "draft" if mr.draft else mr.state,
            "source_branch": mr.source_branch,
            "target_branch": mr.target_branch,
            "url": mr.url,
            "tags": ["mr"],
        }
        if mr.author:
            frontmatter["author"] = f"[[{slug(mr.author)}]]"
        if issue:
            frontmatter["issue"] = issue.key
        if sprint_name:
            frontmatter["sprint"] = f"[[{slug(sprint_name)}]]"

        self.vault.upsert(
            title=title,
            kind="mr",
            frontmatter=frontmatter,
            intro=summary,
            blocks={"facts": f"## Facts\n\n" + "\n".join(facts)},
        )

        if mr.author:
            self._touch_person(mr.author, mr_title=title)
        return title

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
        mr_title: str = "",
        decision_title: str = "",
    ) -> None:
        """Ensure a person note exists. Their history comes from backlinks, so
        nothing needs appending -- Obsidian derives it."""
        member = self.config.member_by(name)
        frontmatter: dict[str, Any] = {"type": "person", "tags": ["person"]}
        if member:
            frontmatter.update(
                {"jira": member.jira, "gitlab": member.gitlab, "capacity": member.capacity}
            )

        existing = self.vault.read(name)
        intro = "" if existing else (
            "One-on-ones, growth notes and context live here. "
            "Sprints, merge requests and decisions link back automatically — "
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
    def sync_all(self, sprints_back: int = 3, include_mrs: bool = True) -> dict[str, Any]:
        """Pull recent sprints and open MRs into the vault in one pass."""
        jira = JiraClient(self.config)
        written: dict[str, list[str]] = {"sprints": [], "merge_requests": [], "people": []}

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
                self.sync_sprint(sprint, issues, jira.workload(sprint.id), jira.done_in(sprint))
            )

        if include_mrs and self.config.gitlab_default_project:
            gitlab = GitLabClient(self.config)
            project = self.config.gitlab_default_project
            for mr in gitlab.list_merge_requests(state="opened", limit=30):
                key = extract_issue_key(mr.source_branch, mr.title)
                issue = None
                if key:
                    try:
                        issue = jira.get_issue(key)
                    except Exception:  # a branch may name an issue that no longer exists
                        issue = None
                written["merge_requests"].append(self.sync_merge_request(mr, project, issue))

        written["people"] = [n.title for n in self.vault.notes("person")]
        return {"written": written, "stats": self.vault.stats()}
