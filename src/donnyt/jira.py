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

# A sprint counts as estimated when at least this share of its issues has
# points. Only those sprints feed the points average: an unestimated sprint's
# "0 points completed" says nothing about how much the team finished.
ESTIMATED_SHARE = 0.8


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
    description: str = ""  # only when the issue was fetched on its own

    def as_dict(self) -> dict[str, Any]:
        extra = {"description": self.description} if self.description else {}
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
            **extra,
        }


def adf_text(node: Any) -> str:
    """Plain text from an Atlassian Document Format tree -- Cloud's rich text.

    Data Center returns wiki markup as a string, which passes straight through.
    """
    if isinstance(node, str):
        return node
    if not isinstance(node, dict):
        return ""
    kind = node.get("type")
    if kind == "text":
        return node.get("text", "")
    if kind == "hardBreak":
        return "\n"
    inner = "".join(adf_text(child) for child in node.get("content") or [])
    if kind == "listItem":
        return "- " + inner.strip() + "\n"
    if kind in ("paragraph", "heading", "codeBlock", "blockquote", "rule"):
        return inner.strip() + "\n\n"
    return inner


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
        self._epic_field: str | None = None

    @property
    def epic_field(self) -> str:
        """Data Center's Epic Link field id, looked up by name on first use.

        Cloud links an issue to its epic through ``parent``, which every query
        already reads, so this is empty there.
        """
        if self._epic_field is None:
            self._epic_field = ""
            if not self.cloud:
                self._epic_field = self.config.epic_link_field or next(
                    (f["id"] for f in self.fields() if f["name"] == "Epic Link"), ""
                )
        return self._epic_field

    def _issue_fields(self) -> list[str]:
        base = ["summary", "status", "issuetype", "assignee", "priority", "labels", "parent", self.points_field]
        return base + [self.epic_field] if self.epic_field else base

    # -- issues ------------------------------------------------------------
    def search(self, jql: str, limit: int = 100) -> list[Issue]:
        """Run JQL, paging until ``limit``.

        Cloud retired offset paging in favour of ``/search/jql`` with page
        tokens; Data Center only has the offset form. Same results either way.
        """
        fields = self._issue_fields()
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
            params={"maxResults": limit, "fields": ",".join(self._issue_fields())},
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

    def update_sprint(
        self,
        sprint_id: int,
        name: str | None = None,
        goal: str | None = None,
        start: str | None = None,
        end: str | None = None,
    ) -> Sprint:
        """Change a sprint's name, goal or dates. Fields left as None are kept.

        The agile API's POST is a partial update (its PUT replaces the whole
        sprint), and it is the same on Cloud and Data Center.
        """
        payload: dict[str, Any] = {}
        if name is not None:
            payload["name"] = name
        if goal is not None:
            payload["goal"] = goal
        if start is not None:
            payload["startDate"] = start
        if end is not None:
            payload["endDate"] = end
        return self._to_sprint(self.http.post(f"/rest/agile/1.0/sprint/{sprint_id}", json_body=payload))

    def assign(self, key: str, user: str | None) -> None:
        """Assign an issue, or unassign it when ``user`` is None.

        ``user`` is the roster's ``jira`` value: an accountId on Cloud, a
        username on Data Center, which has no accountIds.
        """
        body = {"accountId": user} if self.cloud else {"name": user}
        self.http.put(f"{self.api}/issue/{key}/assignee", json_body=body)

    # -- analysis ----------------------------------------------------------
    def velocity(self, board_id: int | None = None, sprints_back: int = 5) -> dict[str, Any]:
        """Completed work per closed sprint, in issues and in points, plus the means.

        This is what sprint planning should size against -- what the team
        actually finished, not what it committed to. Issue counts are always
        there; the points mean covers only sprints that were estimated, so a
        team that has not started estimating gets ``None`` rather than 0.
        """
        closed = self.sprints(board_id, state="closed")
        recent = sorted(closed, key=lambda s: (s.end or "", s.id), reverse=True)[:sprints_back]

        history = []
        for sprint in reversed(recent):
            members = self._sprint_members(sprint.id)
            issues = [issue for issue, _ in members]
            # Jira keeps every sprint an issue sat in, and status is today's.
            # An issue that spilled over is done now but was finished in its
            # last sprint only -- count it there, not in every sprint it passed.
            done = [
                issue for issue, last in members
                if last == sprint.id and issue.status in self.config.done_statuses
            ]
            unestimated = sum(1 for i in issues if i.points is None)
            history.append(
                {
                    "sprint": sprint.name,
                    "id": sprint.id,
                    "ended": sprint.end,
                    "committed_points": sum(i.points or 0 for i in issues),
                    "completed_points": sum(i.points or 0 for i in done),
                    "issues_done": len(done),
                    "issues_total": len(issues),
                    "issues_unestimated": unestimated,
                    "estimated": bool(issues) and (len(issues) - unestimated) / len(issues) >= ESTIMATED_SHARE,
                }
            )

        def mean(values: list[float]) -> float | None:
            return round(sum(values) / len(values), 1) if values else None

        estimated = [h for h in history if h["estimated"]]
        return {
            "history": history,
            "sprints_sampled": len(history),
            "average_completed_issues": mean([h["issues_done"] for h in history]),
            "average_completed_points": mean([h["completed_points"] for h in estimated]),
            "estimated_sprints": len(estimated),
        }

    def done_in(self, sprint: Sprint) -> list[Issue]:
        """Issues finished in ``sprint``.

        For a closed sprint that means done *and* not carried into a later
        sprint, as in ``velocity``. An open sprint still holds its issues, so
        today's status is the answer there.
        """
        done = self.config.done_statuses
        if sprint.state != "closed":
            return [i for i in self.sprint_issues(sprint.id) if i.status in done]
        return [i for i, last in self._sprint_members(sprint.id) if last == sprint.id and i.status in done]

    def workload(self, sprint_id: int) -> dict[str, Any]:
        """Issues and points per assignee in a sprint, measured against configured capacity.

        Unestimated issues are counted, not treated as zero-point work.
        """
        issues = self.sprint_issues(sprint_id)
        per_person: dict[str, dict[str, Any]] = {}
        for issue in issues:
            who = issue.assignee or "Unassigned"
            entry = per_person.setdefault(
                who, {"assignee": who, "points": 0.0, "issues": 0, "unestimated": 0}
            )
            entry["points"] += issue.points or 0
            entry["issues"] += 1
            entry["unestimated"] += issue.points is None

        for entry in per_person.values():
            member = self.config.member_by(entry["assignee"])
            capacity = member.capacity if member else 0.0
            entry["capacity"] = capacity
            # Points say nothing about someone whose work is all unestimated.
            estimated = entry["unestimated"] < entry["issues"]
            entry["over_by"] = round(entry["points"] - capacity, 1) if capacity and estimated else None

        return {
            "sprint_id": sprint_id,
            "issues": len(issues),
            "unestimated_issues": sum(1 for i in issues if i.points is None),
            "total_points": round(sum(e["points"] for e in per_person.values()), 1),
            "team_capacity": self.config.total_capacity,
            "by_assignee": sorted(per_person.values(), key=lambda e: (-e["points"], -e["issues"])),
        }

    # -- internals ---------------------------------------------------------
    def _sprint_members(self, sprint_id: int) -> list[tuple[Issue, int | None]]:
        """Issues ever in a sprint, each with the id of the last sprint it sat in.

        The agile API returns ``closedSprints`` and the current ``sprint`` in the
        same shape on Cloud and Data Center. The last sprint is None while the
        issue is still in an active or future sprint -- it was not finished in
        any closed one.
        """
        fields = ",".join(self._issue_fields() + ["sprint", "closedSprints"])
        members: list[tuple[Issue, int | None]] = []
        while True:
            data = self.http.get(
                f"/rest/agile/1.0/sprint/{sprint_id}/issue",
                params={"fields": fields, "maxResults": 50, "startAt": len(members)},
            )
            batch = data.get("issues", [])
            for raw in batch:
                f = raw.get("fields", {}) or {}
                closed = f.get("closedSprints") or []
                if f.get("sprint"):
                    last = None
                elif closed:
                    last = int(max(closed, key=lambda s: (s.get("endDate") or "", s.get("id", 0)))["id"])
                else:
                    last = sprint_id
                members.append((self._to_issue(raw), last))
            if not batch or len(members) >= int(data.get("total", 0)):
                return members

    def _to_issue(self, raw: dict[str, Any]) -> Issue:
        fields = raw.get("fields", {}) or {}
        assignee = fields.get("assignee") or {}
        parent = fields.get("parent") or {}
        # Data Center: an epic's children carry its key in Epic Link, not parent.
        epic = fields.get(self.epic_field) if self.epic_field else None
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
            parent=parent.get("key", "") or (epic if isinstance(epic, str) else ""),
            url=f"{self.site}/browse/{raw.get('key', '')}",
            description=adf_text(fields.get("description")).strip(),
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
