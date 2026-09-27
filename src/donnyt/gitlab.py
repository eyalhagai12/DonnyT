"""GitLab REST v4 client, read-only: the team's history of merged work.

DonnyT does not write merge requests. It reads them, to record who did what
in a sprint and, later, to estimate new work from what similar work touched.

Project references are URL-encoded paths (``group/subgroup/repo`` becomes
``group%2Fsubgroup%2Frepo``) or numeric ids; :meth:`GitLabClient._ref` handles
both so callers can pass whichever they have.
"""

from __future__ import annotations

import urllib.parse
from dataclasses import dataclass
from typing import Any

from ._http import JSONClient
from .config import Config, load_config


@dataclass
class MergeRequest:
    iid: int
    title: str
    state: str
    source_branch: str
    target_branch: str
    author: str  # GitLab username; resolve it through the roster for a name
    url: str
    draft: bool = False
    merged_at: str = ""
    merged_by: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "iid": self.iid,
            "title": self.title,
            "state": self.state,
            "source_branch": self.source_branch,
            "target_branch": self.target_branch,
            "author": self.author,
            "draft": self.draft,
            "merged_at": self.merged_at,
            "merged_by": self.merged_by,
            "url": self.url,
        }


class GitLabClient:
    def __init__(self, config: Config | None = None) -> None:
        self.config = config or load_config()
        self.url = self.config.gitlab_url
        self.http = JSONClient(
            f"{self.url}/api/v4",
            headers={"PRIVATE-TOKEN": self.config.gitlab_token},
        )

    def _ref(self, project: str | None = None) -> str:
        target = project or self.config.gitlab_default_project
        if not target:
            raise ValueError(
                "No GitLab project given and gitlab.default_project is unset in config.toml."
            )
        return urllib.parse.quote(str(target), safe="")

    def get_project(self, project: str | None = None) -> dict[str, Any]:
        data = self.http.get(f"/projects/{self._ref(project)}")
        return {
            "id": data.get("id"),
            "path": data.get("path_with_namespace"),
            "default_branch": data.get("default_branch"),
            "url": data.get("web_url"),
        }

    def list_merge_requests(
        self,
        project: str | None = None,
        state: str = "opened",
        author: str | None = None,
        limit: int = 30,
    ) -> list[MergeRequest]:
        data = self.http.get(
            f"/projects/{self._ref(project)}/merge_requests",
            params={"state": state, "author_username": author, "per_page": limit},
        )
        return [self._to_mr(item) for item in data]

    def merged_between(self, start: str, end: str, project: str | None = None) -> list[MergeRequest]:
        """MRs merged from ``start`` to ``end`` (``YYYY-MM-DD``, both inclusive), oldest first.

        The API cannot filter on merge time, only on last update, which is at
        or after the merge -- so fetch everything updated since ``start`` and
        keep what was merged inside the window.
        """
        found: list[MergeRequest] = []
        page = 1
        while True:
            batch = self.http.get(
                f"/projects/{self._ref(project)}/merge_requests",
                params={"state": "merged", "updated_after": f"{start}T00:00:00Z",
                        "per_page": 100, "page": page},
            )
            found.extend(self._to_mr(item) for item in batch)
            if len(batch) < 100:
                break
            page += 1
        inside = [mr for mr in found if start <= mr.merged_at[:10] <= end]
        return sorted(inside, key=lambda mr: mr.merged_at)

    def approvers(self, iid: int, project: str | None = None) -> list[str]:
        """Usernames of everyone who approved an MR."""
        data = self.http.get(f"/projects/{self._ref(project)}/merge_requests/{iid}/approvals")
        return [
            ((a.get("user") or {}).get("username", ""))
            for a in (data.get("approved_by") or [])
            if (a.get("user") or {}).get("username")
        ]

    def merge_request_changes(self, iid: int, project: str | None = None) -> dict[str, Any]:
        """File-level change summary for an MR."""
        data = self.http.get(f"/projects/{self._ref(project)}/merge_requests/{iid}/diffs")
        files = [
            {
                "path": d.get("new_path"),
                "new_file": d.get("new_file"),
                "deleted_file": d.get("deleted_file"),
                "renamed_file": d.get("renamed_file"),
            }
            for d in (data if isinstance(data, list) else [])
        ]
        return {"iid": iid, "files_changed": len(files), "files": files}

    def _to_mr(self, raw: dict[str, Any]) -> MergeRequest:
        return MergeRequest(
            iid=int(raw.get("iid", 0)),
            title=raw.get("title", ""),
            state=raw.get("state", ""),
            source_branch=raw.get("source_branch", ""),
            target_branch=raw.get("target_branch", ""),
            author=((raw.get("author") or {}).get("username", "")),
            url=raw.get("web_url", ""),
            draft=bool(raw.get("draft", False)),
            merged_at=raw.get("merged_at") or "",
            merged_by=((raw.get("merged_by") or raw.get("merge_user") or {}).get("username", "")),
        )
