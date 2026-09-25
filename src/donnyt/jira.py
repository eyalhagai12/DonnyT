"""Jira REST client, for Cloud and Data Center, scoped to sprint planning.

Two APIs are in play and the split is not obvious from the outside:

* ``/rest/api/3`` (Cloud) or ``/rest/api/2`` (Data Center) -- issues, JQL
  search, fields. Data Center has no v3.
* ``/rest/agile/1.0`` -- boards, sprints, backlog. Sprints only exist here, and
  it is the same on both.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ._http import JSONClient
from .config import Config, load_config


@dataclass
class Issue:
    key: str
    summary: str
    status: str
    issue_type: str
    assignee: str
    points: float | None
    priority: str
    labels: list[str] = field(default_factory=list)
    parent: str = ""
    url: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "summary": self.summary,
            "status": self.status,
            "type": self.issue_type,
            "assignee": self.assignee,
            "points": self.points,
            "priority": self.priority,
            "labels": self.labels,
            "parent": self.parent,
            "url": self.url,
        }


@dataclass
class Sprint:
    id: int
    name: str
    state: str
    start: str = ""
    end: str = ""
    goal: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "state": self.state,
            "start": self.start,
            "end": self.end,
            "goal": self.goal,
        }


class JiraClient:
    def __init__(self, config: Config | None = None) -> None:
        self.config = config or load_config()
        self.site = self.config.jira_url
        self.cloud = self.config.atlassian_deployment == "cloud"
        self.api = "/rest/api/3" if self.cloud else "/rest/api/2"
        self.http = JSONClient(self.site, headers=self.config.atlassian_headers("jira"))
        self.points_field = self.config.story_points_field

    # -- issues ------------------------------------------------------------
    def search(self, jql: str, limit: int = 100) -> list[Issue]:
        """Run JQL, paging until ``limit``.

        Cloud retired offset paging in favour of ``/search/jql`` with page
        tokens; Data Center only has the offset form. Same results either way.
        """
        fields = [
            "summary",
            "status",
            "issuetype",
            "assignee",
            "priority",
            "labels",
            "parent",
            self.points_field,
        ]
        issues: list[Issue] = []
        next_token: str | None = None

        while len(issues) < limit:
            payload: dict[str, Any] = {
                "jql": jql,
                "maxResults": min(100, limit - len(issues)),
                "fields": fields,
            }
            if self.cloud:
                if next_token:
                    payload["nextPageToken"] = next_token
                data = self.http.post(f"{self.api}/search/jql", json_body=payload)
            else:
                payload["startAt"] = len(issues)
                data = self.http.post(f"{self.api}/search", json_body=payload)

            batch = data.get("issues", [])
            issues.extend(self._to_issue(raw) for raw in batch)
            if not batch:
                break

            if self.cloud:
                next_token = data.get("nextPageToken")
                if data.get("isLast", True) or not next_token:
                    break
            elif len(issues) >= int(data.get("total", 0)):
                break

        return issues[:limit]

    def get_issue(self, key: str) -> Issue:
        data = self.http.get(f"{self.api}/issue/{key}")
        return self._to_issue(data)

    def fields(self) -> list[dict[str, Any]]:
        """Every field on the site, id and name -- for finding story points."""
        data = self.http.get(f"{self.api}/field")
        return [
            {"id": f.get("id", ""), "name": f.get("name", "")}
            for f in (data if isinstance(data, list) else [])
        ]

    # -- boards and sprints ------------------------------------------------
    def boards(self) -> list[dict[str, Any]]:
        data = self.http.get(
            "/rest/agile/1.0/board", params={"projectKeyOrId": self.config.jira_project_key}
        )
        return [
            {"id": b.get("id"), "name": b.get("name"), "type": b.get("type")}
            for b in data.get("values", [])
        ]

    def sprints(self, board_id: int | None = None, state: str | None = None) -> list[Sprint]:
        """Every sprint on the board, oldest first.

        The endpoint pages at 50 in id order, so a single request on a long-lived
        board returns only the oldest sprints -- page through all of them.
        """
        board = board_id or self.config.jira_board_id
        found: list[Sprint] = []
        while True:
            data = self.http.get(
                f"/rest/agile/1.0/board/{board}/sprint",
                params={"state": state, "maxResults": 50, "startAt": len(found)},
            )
            batch = data.get("values", [])
            found.extend(self._to_sprint(s) for s in batch)
            if data.get("isLast", True) or not batch:
                return found

    def active_sprint(self, board_id: int | None = None) -> Sprint | None:
        found = self.sprints(board_id, state="active")
        return found[0] if found else None

    def next_sprint(self, board_id: int | None = None) -> Sprint | None:
        """The nearest future sprint, by start date then id."""
        future = self.sprints(board_id, state="future")
        if not future:
            return None
        return sorted(future, key=lambda s: (s.start or "9999", s.id))[0]

    def sprint_issues(self, sprint_id: int, limit: int = 200) -> list[Issue]:
        return self.search(f"sprint = {sprint_id} ORDER BY rank", limit=limit)

    def backlog(self, board_id: int | None = None, limit: int = 100) -> list[Issue]:
        """Board backlog in rank order -- what a planning session picks from."""
        board = board_id or self.config.jira_board_id
        data = self.http.get(
            f"/rest/agile/1.0/board/{board}/backlog",
            params={"maxResults": limit, "fields": "summary,status,issuetype,assignee,priority,labels,parent," + self.points_field},
        )
        return [self._to_issue(raw) for raw in data.get("issues", [])]

    def create_sprint(
        self,
        name: str,
        board_id: int | None = None,
        start: str | None = None,
        end: str | None = None,
        goal: str = "",
    ) -> Sprint:
        payload: dict[str, Any] = {
            "name": name,
            "originBoardId": board_id or self.config.jira_board_id,
        }
        if start:
            payload["startDate"] = start
        if end:
            payload["endDate"] = end
        if goal:
            payload["goal"] = goal
        return self._to_sprint(self.http.post("/rest/agile/1.0/sprint", json_body=payload))

    def move_issues_to_sprint(self, sprint_id: int, issue_keys: list[str]) -> dict[str, Any]:
        """Jira caps this at 50 issues per call, so batch."""
        moved = 0
        for start in range(0, len(issue_keys), 50):
            chunk = issue_keys[start : start + 50]
            self.http.post(f"/rest/agile/1.0/sprint/{sprint_id}/issue", json_body={"issues": chunk})
            moved += len(chunk)
        return {"sprint_id": sprint_id, "moved": moved, "issues": issue_keys}

    # -- analysis ----------------------------------------------------------
    def velocity(self, board_id: int | None = None, sprints_back: int = 5) -> dict[str, Any]:
        """Completed points per closed sprint, plus the mean.

        This is the number sprint planning should size against -- what the team
        actually finished, not what it committed to.
        """
        closed = self.sprints(board_id, state="closed")
        recent = sorted(closed, key=lambda s: (s.end or "", s.id), reverse=True)[:sprints_back]

        history = []
        for sprint in reversed(recent):
            issues = self.sprint_issues(sprint.id)
            done = [i for i in issues if i.status in self.config.done_statuses]
            completed = sum(i.points or 0 for i in done)
            committed = sum(i.points or 0 for i in issues)
            history.append(
                {
                    "sprint": sprint.name,
                    "id": sprint.id,
                    "ended": sprint.end,
                    "committed_points": committed,
                    "completed_points": completed,
                    "issues_done": len(done),
                    "issues_total": len(issues),
                }
            )

        completed_values = [h["completed_points"] for h in history]
        average = round(sum(completed_values) / len(completed_values), 1) if completed_values else 0.0
        return {"history": history, "average_completed_points": average, "sprints_sampled": len(history)}

    def workload(self, sprint_id: int) -> dict[str, Any]:
        """Points per assignee in a sprint, measured against configured capacity."""
        issues = self.sprint_issues(sprint_id)
        per_person: dict[str, dict[str, Any]] = {}
        for issue in issues:
            who = issue.assignee or "Unassigned"
            entry = per_person.setdefault(who, {"assignee": who, "points": 0.0, "issues": 0})
            entry["points"] += issue.points or 0
            entry["issues"] += 1

        for entry in per_person.values():
            member = self.config.member_by(entry["assignee"])
            capacity = member.capacity if member else 0.0
            entry["capacity"] = capacity
            entry["over_by"] = round(entry["points"] - capacity, 1) if capacity else None

        return {
            "sprint_id": sprint_id,
            "total_points": round(sum(e["points"] for e in per_person.values()), 1),
            "team_capacity": self.config.total_capacity,
            "by_assignee": sorted(per_person.values(), key=lambda e: -e["points"]),
        }

    # -- internals ---------------------------------------------------------
    def _to_issue(self, raw: dict[str, Any]) -> Issue:
        fields = raw.get("fields", {}) or {}
        assignee = fields.get("assignee") or {}
        parent = fields.get("parent") or {}
        points = fields.get(self.points_field)
        return Issue(
            key=raw.get("key", ""),
            summary=fields.get("summary", ""),
            status=((fields.get("status") or {}).get("name", "")),
            issue_type=((fields.get("issuetype") or {}).get("name", "")),
            assignee=assignee.get("displayName", ""),
            points=float(points) if isinstance(points, (int, float)) else None,
            priority=((fields.get("priority") or {}).get("name", "")),
            labels=list(fields.get("labels") or []),
            parent=parent.get("key", ""),
            url=f"{self.site}/browse/{raw.get('key', '')}",
        )

    @staticmethod
    def _to_sprint(raw: dict[str, Any]) -> Sprint:
        return Sprint(
            id=int(raw.get("id", 0)),
            name=raw.get("name", ""),
            state=raw.get("state", ""),
            start=(raw.get("startDate") or "")[:10],
            end=(raw.get("endDate") or "")[:10],
            goal=raw.get("goal") or "",
        )


def today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")
