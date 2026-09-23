"""Configuration loading.

Two files at the repo root, neither committed:

* ``.env``        -- credentials only (API tokens).
* ``config.toml`` -- everything else (site URLs, project keys, team roster).

TOML is read with the stdlib ``tomllib`` and ``.env`` with a small parser below,
so configuration costs no third-party dependency. ``config.example.toml`` and
``.env.example`` are the tracked templates.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any


class ConfigError(RuntimeError):
    """Configuration or credentials are missing, empty, or malformed."""


# The repo always has this file; an installed copy in site-packages never does.
_MARKER = "config.example.toml"


def _find_marker(start: Path) -> Path | None:
    for candidate in (start, *start.parents):
        if (candidate / _MARKER).exists():
            return candidate
    return None


def repo_root() -> Path:
    """Locate the repo root -- where .env and config.toml live.

    Deriving this from ``__file__`` alone breaks once the package is installed
    into a virtualenv, because the module then sits in site-packages rather
    than in the checkout. So look, in order, at an explicit override, the
    working directory, and only then the module's own location (which is
    correct for a source or editable install).
    """
    override = os.environ.get("DONNYT_HOME", "").strip()
    if override:
        path = Path(override).expanduser()
        if not path.exists():
            raise ConfigError(f"DONNYT_HOME points at {path}, which does not exist.")
        return path.resolve()

    for start in (Path.cwd(), Path(__file__).resolve().parent):
        found = _find_marker(start.resolve())
        if found:
            return found

    # Nothing matched: fall back to the source-layout guess so the error
    # messages name a plausible path rather than something meaningless.
    return Path(__file__).resolve().parents[2]


def load_env_file(path: Path) -> None:
    """Load ``KEY=value`` pairs into os.environ without overwriting real env vars."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key, value)


@dataclass
class TeamMember:
    name: str
    jira: str = ""
    gitlab: str = ""
    capacity: float = 0.0


@dataclass
class Config:
    raw: dict[str, Any]
    root: Path
    members: list[TeamMember] = field(default_factory=list)

    # -- atlassian ---------------------------------------------------------
    @property
    def atlassian_site(self) -> str:
        site = str(self._get("atlassian.site", required=True)).rstrip("/")
        if not site.startswith("http"):
            raise ConfigError(f"atlassian.site must be a full URL, got {site!r}")
        return site

    @property
    def atlassian_auth(self) -> tuple[str, str]:
        email = os.environ.get("ATLASSIAN_EMAIL", "").strip()
        token = os.environ.get("ATLASSIAN_API_TOKEN", "").strip()
        if not email or not token:
            raise ConfigError(
                "ATLASSIAN_EMAIL and ATLASSIAN_API_TOKEN must be set in .env.\n"
                "Create a token at: https://id.atlassian.com/manage-profile/security/api-tokens\n"
                "See INSTALL.md step 4."
            )
        return email, token

    # -- confluence --------------------------------------------------------
    @property
    def confluence_space(self) -> str:
        return str(self._get("confluence.space", default=""))

    @property
    def mr_template_page_id(self) -> str:
        return str(self._get("confluence.mr_template_page_id", default="") or "")

    @property
    def mr_template_title(self) -> str:
        return str(self._get("confluence.mr_template_title", default="Merge Request Template"))

    @property
    def sprint_plan_parent_page_id(self) -> str:
        return str(self._get("confluence.sprint_plan_parent_page_id", default="") or "")

    # -- jira --------------------------------------------------------------
    @property
    def jira_project_key(self) -> str:
        return str(self._get("jira.project_key", required=True))

    @property
    def jira_board_id(self) -> int:
        board = self._get("jira.board_id", default=0)
        if not board:
            raise ConfigError(
                "jira.board_id is not set in config.toml. Find it in your board URL:\n"
                "  <site>/jira/software/projects/<KEY>/boards/<id>"
            )
        return int(board)

    @property
    def story_points_field(self) -> str:
        return str(self._get("jira.story_points_field", default="customfield_10016"))

    @property
    def done_statuses(self) -> list[str]:
        return [str(s) for s in self._get("jira.done_statuses", default=["Done", "Closed", "Resolved"])]

    # -- gitlab ------------------------------------------------------------
    @property
    def gitlab_url(self) -> str:
        return str(self._get("gitlab.url", default="https://gitlab.com")).rstrip("/")

    @property
    def gitlab_token(self) -> str:
        token = os.environ.get("GITLAB_TOKEN", "").strip()
        if not token:
            raise ConfigError(
                "GITLAB_TOKEN must be set in .env (scopes: api, read_repository).\n"
                "See INSTALL.md step 4."
            )
        return token

    @property
    def gitlab_default_project(self) -> str:
        return str(self._get("gitlab.default_project", default="") or "")

    @property
    def gitlab_target_branch(self) -> str:
        return str(self._get("gitlab.default_target_branch", default="main"))

    # -- vault -------------------------------------------------------------
    @property
    def vault_path(self) -> Path:
        path = Path(str(self._get("vault.path", default="vault")))
        return path if path.is_absolute() else (self.root / path)

    # -- helpers -----------------------------------------------------------
    def _get(self, dotted: str, default: Any = None, required: bool = False) -> Any:
        node: Any = self.raw
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                if required:
                    raise ConfigError(f"[{dotted.rsplit('.', 1)[0]}] {dotted} is missing from config.toml")
                return default
            node = node[part]
        if node in (None, "") and required:
            raise ConfigError(f"{dotted} is empty in config.toml")
        return default if node is None else node

    def member_by(self, handle: str) -> TeamMember | None:
        """Look a member up by name, Jira account id, or GitLab username."""
        needle = handle.strip().lower()
        if not needle:
            return None
        for member in self.members:
            candidates = {member.name.lower(), member.jira.lower(), member.gitlab.lower()} - {""}
            if needle in candidates:
                return member
        return None

    @property
    def total_capacity(self) -> float:
        return sum(m.capacity for m in self.members)


@lru_cache(maxsize=1)
def load_config() -> Config:
    root = repo_root()
    load_env_file(root / ".env")

    config_file = root / "config.toml"
    if not config_file.exists():
        raise ConfigError(
            f"{config_file} not found.\n"
            "Copy config.example.toml to config.toml and fill it in (INSTALL.md step 5)."
        )

    try:
        raw = tomllib.loads(config_file.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"config.toml is not valid TOML: {exc}") from None

    members = [
        TeamMember(
            name=str(entry.get("name", "")),
            jira=str(entry.get("jira", "") or ""),
            gitlab=str(entry.get("gitlab", "") or ""),
            capacity=float(entry.get("capacity", 0) or 0),
        )
        for entry in (raw.get("team", {}) or {}).get("members", []) or []
    ]
    return Config(raw=raw, root=root, members=members)
