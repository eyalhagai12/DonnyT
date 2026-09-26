"""Build the knowledge graph: turn Jira and GitLab facts into linked notes.

Each builder writes one note and, crucially, the edges around it -- a sprint
note links every person who carried work in it, a merge request note links its
author and its Jira issue. That reciprocity is what makes Obsidian's graph view
show the team rather than a pile of files.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from .config import Config, load_config
from .gitlab import GitLabClient, MergeRequest
from .jira import Issue, JiraClient, Sprint
from .vault import Vault, link, slug

# A Jira key embedded in a branch name or MR title, e.g. TEAM-1234.
ISSUE_KEY = re.compile(r"\b([A-Z][A-Z0-9_]+-\d+)\b")


def extract_issue_key(*texts: str) -> str:
    for text in texts:
        match = ISSUE_KEY.search(text or "")
        if match:
            return match.group(1)
    return ""


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
        self, sprint: Sprint, issues: list[Issue], workload: dict[str, Any], done: list[Issue]
    ) -> str:
        """Write the note for one sprint and touch every person it involved.

        ``done`` comes from ``JiraClient.done_in``: today's status alone would
        count spill-over as finished in every sprint it passed through.
        """
        title = sprint.name
        people = sorted({i.assignee for i in issues if i.assignee})

        committed = round(sum(i.points or 0 for i in issues), 1)
        completed = round(sum(i.points or 0 for i in done), 1)

        overview = "\n".join(
            [
                f"- **State** — {sprint.state}",
                f"- **Dates** — {sprint.start or '?'} → {sprint.end or '?'}",
                f"- **Goal** — {sprint.goal or '_not set_'}",
                f"- **Committed** — {committed} pts across {len(issues)} issues",
                f"- **Completed** — {completed} pts across {len(done)} issues",
                f"- **Team** — {', '.join(link(p) for p in people) or '—'}",
            ]
        )

        load_rows = ["| Person | Points | Capacity | Over by |", "| --- | --- | --- | --- |"]
        for entry in workload.get("by_assignee", []):
            who = entry["assignee"]
            name = link(who) if who != "Unassigned" else "Unassigned"
            over = entry.get("over_by")
            load_rows.append(
                f"| {name} | {round(entry['points'], 1)} | {entry.get('capacity') or '—'} "
                f"| {'+' if over and over > 0 else ''}{over if over is not None else '—'} |"
            )

        self.vault.upsert(
            title=title,
            kind="sprint",
            frontmatter={
                "type": "sprint",
                "sprint_id": sprint.id,
                "state": sprint.state,
                "start": sprint.start,
                "end": sprint.end,
                "board": self.config.jira_board_id,
                "committed_points": committed,
                "completed_points": completed,
                "people": [f"[[{slug(p)}]]" for p in people],
                "tags": ["sprint"],
            },
            intro=f"_{sprint.goal}_\n" if sprint.goal else "",
            blocks={
                "overview": f"## Overview\n\n{overview}",
                "workload": "## Workload\n\n" + "\n".join(load_rows),
                "issues": f"## Issues\n\n{_issue_table(issues)}",
            },
        )

        for person in people:
            self._touch_person(person, sprint_title=title)

        return title

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
            "check the backlinks pane for their history.\n"
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
