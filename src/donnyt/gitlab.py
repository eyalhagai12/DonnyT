"""GitLab REST v4 client, read-only: the team's history of merged work.

DonnyT does not write merge requests. It reads them -- across every repo in
``[[gitlab.repos]]`` -- to record who did what in a sprint, and to estimate new
work from what similar past work actually changed.

Project references are URL-encoded paths (``group/subgroup/repo`` becomes
``group%2Fsubgroup%2Frepo``) or numeric ids; :meth:`GitLabClient._ref` handles
both so callers can pass whichever they have.
"""

from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass, field
from typing import Any

from ._http import JSONClient
from .config import Config, load_config


@dataclass
class Change:
    """What one ticket actually changed in one repo -- the evidence an estimate
    compares against."""

    project: str
    source: str  # "mr" when found through merged MRs, "commits" when pushed directly
    refs: list[str] = field(default_factory=list)  # MR iids or commit short ids
    files: list[str] = field(default_factory=list)
    additions: int = 0
    deletions: int = 0

    @property
    def areas(self) -> list[str]:
        """Folders touched (two levels for deep paths), most-touched first."""
        counts: dict[str, int] = {}
        for path in self.files:
            parts = path.split("/")
            area = "/".join(parts[:2]) if len(parts) > 2 else (parts[0] if len(parts) > 1 else ".")
            counts[area] = counts.get(area, 0) + 1
        return sorted(counts, key=lambda a: -counts[a])

    def as_dict(self) -> dict[str, Any]:
        return {
            "project": self.project,
            "source": self.source,
            "refs": self.refs,
            "files_changed": len(self.files),
            "lines_added": self.additions,
            "lines_removed": self.deletions,
            "areas": self.areas,
            "files": self.files[:30],
        }


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
    project: str = ""  # group/repo, so !5 in one repo is not confused with !5 in another

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
            "project": self.project,
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
        return [self._to_mr(item, project) for item in data]

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
            found.extend(self._to_mr(item, project) for item in batch)
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

    def work_for_issue(self, key: str, project: str | None = None) -> Change | None:
        """What an issue changed in a repo, or None if nothing mentions it.

        Merged MRs whose title or branch carries the key come first. Without
        any, commits on the default branch whose message carries it -- history
        pushed without MRs. Merge commits are skipped so nothing counts twice.
        """
        target = project or self.config.gitlab_default_project
        pattern = re.compile(r"\b" + re.escape(key) + r"\b")
        mrs = [
            mr for mr in self.http.get(
                f"/projects/{self._ref(target)}/merge_requests",
                params={"state": "merged", "search": key, "per_page": 20},
            ) or []
            if pattern.search(mr.get("title", "")) or pattern.search(mr.get("source_branch", ""))
        ]
        if mrs:
            change = Change(project=target, source="mr")
            files: set[str] = set()
            for mr in mrs:
                change.refs.append(f"!{mr['iid']}")
                for diff in self.http.get(
                    f"/projects/{self._ref(target)}/merge_requests/{mr['iid']}/diffs",
                    params={"per_page": 100},
                ) or []:
                    files.add(diff.get("new_path") or diff.get("old_path", ""))
                    added, removed = _count_lines(diff.get("diff", ""))
                    change.additions += added
                    change.deletions += removed
            change.files = sorted(files)
            return change

        commits = [
            c for c in self.http.get(
                f"/projects/{self._ref(target)}/repository/commits",
                params={"with_stats": "true", "per_page": 100},
            ) or []
            if pattern.search(c.get("message", "")) and len(c.get("parent_ids") or []) < 2
        ]
        if not commits:
            return None
        change = Change(project=target, source="commits")
        files = set()
        for commit in commits:
            change.refs.append(commit.get("short_id", ""))
            stats = commit.get("stats") or {}
            change.additions += int(stats.get("additions", 0))
            change.deletions += int(stats.get("deletions", 0))
            for diff in self.http.get(
                f"/projects/{self._ref(target)}/repository/commits/{commit['id']}/diff",
                params={"per_page": 100},
            ) or []:
                files.add(diff.get("new_path") or diff.get("old_path", ""))
        change.files = sorted(files)
        return change

    def tree(self, project: str | None = None, depth: int = 2) -> list[str]:
        """The repo's folders and files, ``depth`` levels deep: where things live."""
        target = project or self.config.gitlab_default_project
        paths: list[str] = []
        page = 1
        while True:
            batch = self.http.get(
                f"/projects/{self._ref(target)}/repository/tree",
                params={"recursive": "true", "per_page": 100, "page": page},
            ) or []
            paths.extend(
                item["path"] + ("/" if item.get("type") == "tree" else "")
                for item in batch if item["path"].count("/") < depth
            )
            if len(batch) < 100:
                return sorted(paths)
            page += 1

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

    def _to_mr(self, raw: dict[str, Any], project: str | None = None) -> MergeRequest:
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
            project=project or self.config.gitlab_default_project,
        )


def _count_lines(diff: str) -> tuple[int, int]:
    """Added and removed lines in a unified diff, headers excluded."""
    added = removed = 0
    for line in diff.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    return added, removed
