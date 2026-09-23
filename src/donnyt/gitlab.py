"""GitLab REST v4 client for merge requests.

Project references are URL-encoded paths (``group/subgroup/repo`` becomes
``group%2Fsubgroup%2Frepo``) or numeric ids; :meth:`GitLabClient._ref` handles
both so callers can pass whichever they have.
"""

from __future__ import annotations

import subprocess
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
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
    author: str
    url: str
    draft: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "iid": self.iid,
            "title": self.title,
            "state": self.state,
            "source_branch": self.source_branch,
            "target_branch": self.target_branch,
            "author": self.author,
            "draft": self.draft,
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

    # -- reads -------------------------------------------------------------
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

    def get_merge_request(self, iid: int, project: str | None = None) -> MergeRequest:
        data = self.http.get(f"/projects/{self._ref(project)}/merge_requests/{iid}")
        return self._to_mr(data)

    def merge_request_changes(self, iid: int, project: str | None = None) -> dict[str, Any]:
        """File-level change summary for an existing MR."""
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

    def compare(self, source: str, target: str, project: str | None = None) -> dict[str, Any]:
        """Commits and touched files between two refs -- the raw material for a description."""
        data = self.http.get(
            f"/projects/{self._ref(project)}/repository/compare",
            params={"from": target, "to": source},
        )
        commits = [
            {
                "id": (c.get("short_id") or ""),
                "title": c.get("title", ""),
                "author": c.get("author_name", ""),
            }
            for c in data.get("commits", [])
        ]
        files = [d.get("new_path") for d in data.get("diffs", [])]
        return {"source": source, "target": target, "commits": commits, "files": files}

    # -- writes ------------------------------------------------------------
    def create_merge_request(
        self,
        source_branch: str,
        title: str,
        description: str,
        target_branch: str | None = None,
        project: str | None = None,
        draft: bool = True,
        labels: list[str] | None = None,
        assignee_id: int | None = None,
        remove_source_branch: bool = True,
    ) -> MergeRequest:
        payload: dict[str, Any] = {
            "source_branch": source_branch,
            "target_branch": target_branch or self.config.gitlab_target_branch,
            "title": f"Draft: {title}" if draft and not title.lower().startswith("draft:") else title,
            "description": description,
            "remove_source_branch": remove_source_branch,
        }
        if labels:
            payload["labels"] = ",".join(labels)
        if assignee_id:
            payload["assignee_id"] = assignee_id
        data = self.http.post(f"/projects/{self._ref(project)}/merge_requests", json_body=payload)
        return self._to_mr(data)

    def update_merge_request(
        self,
        iid: int,
        project: str | None = None,
        title: str | None = None,
        description: str | None = None,
        labels: list[str] | None = None,
    ) -> MergeRequest:
        payload: dict[str, Any] = {}
        if title is not None:
            payload["title"] = title
        if description is not None:
            payload["description"] = description
        if labels is not None:
            payload["labels"] = ",".join(labels)
        if not payload:
            raise ValueError("Nothing to update: pass title, description, or labels.")
        data = self.http.put(
            f"/projects/{self._ref(project)}/merge_requests/{iid}", json_body=payload
        )
        return self._to_mr(data)

    # -- internals ---------------------------------------------------------
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
        )


# -- local git ------------------------------------------------------------
def local_branch_summary(repo: str | Path, target: str = "main") -> dict[str, Any]:
    """Commits and changed files on the current branch versus ``target``.

    Reads the working repo directly so an MR description can be drafted before
    the branch is ever pushed.
    """
    path = Path(repo)

    def git(*args: str) -> str:
        result = subprocess.run(
            ["git", *args], cwd=path, capture_output=True, text=True, check=False
        )
        return result.stdout.strip() if result.returncode == 0 else ""

    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    base = git("merge-base", "HEAD", target) or git("merge-base", "HEAD", f"origin/{target}")
    if not base:
        return {"branch": branch, "target": target, "error": f"No merge base with {target!r}."}

    log = git("log", "--reverse", "--format=%h%x09%an%x09%s", f"{base}..HEAD")
    commits = []
    for line in log.splitlines():
        parts = line.split("\t", 2)
        if len(parts) == 3:
            commits.append({"id": parts[0], "author": parts[1], "title": parts[2]})

    files = [f for f in git("diff", "--name-only", f"{base}..HEAD").splitlines() if f]
    stat = git("diff", "--shortstat", f"{base}..HEAD")

    return {
        "branch": branch,
        "target": target,
        "commits": commits,
        "files": files,
        "diffstat": stat,
    }
