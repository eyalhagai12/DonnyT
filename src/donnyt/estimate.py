"""Evidence for estimating issues: what similar past work really changed.

The estimate itself is a judgement, made by the model with the lead. This
module only gathers what it should rest on, across every repo a ticket maps to
(``[[gitlab.repos]]``, by Jira component or label):

* the issue itself;
* the finished issues most like it -- same components or labels, ranked by
  word overlap -- each with what it actually changed in each repo;
* the layout of the repos it will touch.

Similarity is plain word overlap: stdlib, explainable, and good enough to put
the right five tickets in front of a person. Nothing here writes anywhere.
"""

from __future__ import annotations

import re
from typing import Any

from .config import Config, load_config
from .gitlab import GitLabClient
from .jira import Issue, JiraClient

# Words that say nothing about what a ticket is about.
_STOP = {
    "the", "and", "for", "with", "that", "this", "from", "into", "are", "not", "but", "all",
    "any", "can", "should", "must", "when", "then", "than", "its", "it's", "was", "has",
    "have", "one", "our", "out", "use", "via", "per", "add", "make", "new",
}


def words(text: str) -> set[str]:
    """Lower-cased words of three or more characters, stop words removed."""
    return set(re.findall(r"[a-z][a-z0-9]{2,}", text.lower())) - _STOP


def similarity(a: str, b: str) -> float:
    """Word overlap (Jaccard) between two texts, 0 to 1."""
    wa, wb = words(a), words(b)
    return len(wa & wb) / len(wa | wb) if wa and wb else 0.0


def _text(issue: Issue) -> str:
    return f"{issue.summary} {issue.description}"


def rank_similar(issue: Issue, candidates: list[Issue], limit: int = 5) -> list[tuple[Issue, float]]:
    """The candidates most like ``issue``, best first. The issue itself and
    candidates sharing no words are left out."""
    target = _text(issue)
    scored = [(c, similarity(target, _text(c))) for c in candidates if c.key != issue.key]
    scored = [pair for pair in scored if pair[1] > 0]
    return sorted(scored, key=lambda pair: -pair[1])[:limit]


def size_points(size: str, sizes: dict[str, float]) -> float:
    """Story points for a size name, e.g. ``M`` -> 3. Raises ValueError for an unknown size."""
    key = size.strip().upper()
    if key not in sizes:
        raise ValueError(f"{size!r} is not a size; use one of {', '.join(sizes)}")
    return sizes[key]


def context(
    issue_keys: list[str],
    config: Config | None = None,
    jira: JiraClient | None = None,
    gitlab: GitLabClient | None = None,
    similar: int = 5,
) -> dict[str, Any]:
    """Everything an estimate for each issue should rest on. See the module docstring."""
    config = config or load_config()
    jira = jira or JiraClient(config)
    gitlab_error = ""
    try:
        gitlab = gitlab or (GitLabClient(config) if config.repos else None)
    except Exception as exc:  # no token: estimate from Jira alone, and say so
        gitlab, gitlab_error = None, f"{type(exc).__name__}: {exc}"

    changes: dict[tuple[str, str], dict[str, Any] | None] = {}
    layouts: dict[str, list[str]] = {}

    def change(key: str, project: str) -> dict[str, Any] | None:
        nonlocal gitlab_error
        if gitlab is None:
            return None
        if (key, project) not in changes:
            try:
                found = gitlab.work_for_issue(key, project)
                changes[key, project] = found.as_dict() if found else None
            except Exception as exc:
                gitlab_error = f"{type(exc).__name__}: {exc}"
                changes[key, project] = None
        return changes[key, project]

    def layout(project: str) -> list[str]:
        nonlocal gitlab_error
        if gitlab is not None and project not in layouts:
            try:
                layouts[project] = gitlab.tree(project)
            except Exception as exc:
                gitlab_error = f"{type(exc).__name__}: {exc}"
                layouts[project] = []
        return layouts.get(project, [])

    issues = []
    for key in issue_keys:
        issue = jira.get_issue(key)
        repos = config.repos_for(issue.components, issue.labels)
        pool = jira.done_like(issue.components, issue.labels, limit=50)
        evidence = []
        for other, score in rank_similar(issue, pool, similar):
            their_repos = config.repos_for(other.components, other.labels)
            evidence.append({
                "key": other.key,
                "summary": other.summary,
                "type": other.issue_type,
                "points": other.points,
                "components": other.components,
                "labels": other.labels,
                "similarity": round(score, 2),
                "changes": [c for r in their_repos if (c := change(other.key, r.project))],
            })
        issues.append({
            "issue": issue.as_dict(),
            "repos": [r.project for r in repos],
            "unmapped": not repos,
            "similar": evidence,
            "layout": {r.project: layout(r.project) for r in repos},
        })

    result: dict[str, Any] = {"sizes": config.estimation_sizes, "issues": issues}
    if gitlab_error:
        result["gitlab_error"] = gitlab_error
    return result
