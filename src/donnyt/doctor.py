"""Preflight checks.

Everything that can be wrong on a fresh isolated install -- a missing file, an
unset token, a blocked host, an intercepted TLS handshake -- shows up here with
the exact fix, so setup does not turn into a guessing game.
"""

from __future__ import annotations

import os
import sys
from typing import Any

from .config import ConfigError, load_config, repo_root

OK, FAIL, SKIP = "ok", "fail", "skipped"


def _check(name: str, status: str, detail: str, fix: str = "") -> dict[str, Any]:
    result = {"check": name, "status": status, "detail": detail}
    if fix:
        result["fix"] = fix
    return result


def run_checks() -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    root = repo_root()

    # -- environment -------------------------------------------------------
    version = ".".join(str(n) for n in sys.version_info[:3])
    if sys.version_info >= (3, 11):
        results.append(_check("python", OK, f"Python {version}"))
    else:
        results.append(
            _check(
                "python",
                FAIL,
                f"Python {version} is too old",
                "Python 3.11+ is required (tomllib is used for config). See INSTALL.md step 1.",
            )
        )

    origin = "DONNYT_HOME" if os.environ.get("DONNYT_HOME") else "auto-detected"
    results.append(_check("repo_root", OK, f"{root}  ({origin})"))

    for filename, step in ((".env", "step 4"), ("config.toml", "step 5")):
        path = root / filename
        results.append(
            _check(filename, OK, f"found at {path}")
            if path.exists()
            else _check(
                filename,
                FAIL,
                f"missing at {path}",
                f"Copy {filename}.example -> {filename} and fill it in (INSTALL.md {step}).".replace(
                    "config.toml.example", "config.example.toml"
                ),
            )
        )

    ca = next(
        (
            os.environ[v]
            for v in ("DONNYT_CA_BUNDLE", "REQUESTS_CA_BUNDLE", "SSL_CERT_FILE")
            if os.environ.get(v)
        ),
        "",
    )
    results.append(
        _check("tls_ca_bundle", OK, f"using {ca}")
        if ca
        else _check("tls_ca_bundle", SKIP, "using system trust store")
    )

    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or ""
    results.append(
        _check("proxy", OK, f"HTTPS_PROXY={proxy}") if proxy else _check("proxy", SKIP, "no proxy set")
    )

    # Import the server module rather than just the package: that proves the
    # SDK's API is one this code actually supports, not merely that it exists.
    try:
        from . import mcp_server

        api = type(mcp_server.mcp).__name__
        results.append(_check("mcp_package", OK, f"usable ({api})"))
    except SystemExit as exc:
        results.append(
            _check(
                "mcp_package",
                FAIL,
                str(exc).splitlines()[0],
                "pip install --no-index --find-links vendor/wheels mcp  (INSTALL.md step 3). "
                "The CLI still works without it; only the MCP server needs it.",
            )
        )
    except Exception as exc:
        results.append(
            _check("mcp_package", FAIL, f"{type(exc).__name__}: {exc}",
                   "The installed mcp SDK may be incompatible. See INSTALL.md troubleshooting.")
        )

    # -- config ------------------------------------------------------------
    try:
        config = load_config()
    except ConfigError as exc:
        results.append(_check("config", FAIL, str(exc)))
        return _summarize(results)

    results.append(_check("config", OK, "config.toml parsed"))

    # -- live connectivity -------------------------------------------------
    results.append(_probe_confluence(config))
    results.append(_probe_jira(config))
    results.append(_probe_gitlab(config))
    results.append(_probe_vault(config))

    return _summarize(results)


def _probe_confluence(config: Any) -> dict[str, Any]:
    try:
        from .confluence import ConfluenceClient

        client = ConfluenceClient(config)
        me = client.http.get("/rest/api/user/current")
        detail = f"authenticated as {me.get('displayName') or me.get('email') or 'unknown'}"

        template_id = config.mr_template_page_id
        try:
            page = client.get_template()
            detail += f"; MR template '{page.title}' (id {page.id})"
        except Exception as exc:
            return _check(
                "confluence",
                FAIL,
                f"{detail}; template lookup failed: {exc}",
                "Set confluence.mr_template_page_id in config.toml to the numeric page id "
                f"{'' if template_id else 'of your MR template page'} (INSTALL.md step 5).",
            )
        return _check("confluence", OK, detail)
    except ConfigError as exc:
        return _check("confluence", FAIL, str(exc))
    except Exception as exc:
        return _check(
            "confluence",
            FAIL,
            str(exc),
            "Check atlassian.site in config.toml and ATLASSIAN_* in .env. If the host is "
            "reachable only through a proxy, set HTTPS_PROXY; if TLS is intercepted, set "
            "DONNYT_CA_BUNDLE to your corporate root certificate.",
        )


def _probe_jira(config: Any) -> dict[str, Any]:
    try:
        from .jira import JiraClient

        jira = JiraClient(config)
        boards = jira.boards()
        if not boards:
            return _check(
                "jira",
                FAIL,
                f"no boards visible for project {config.jira_project_key!r}",
                "Check jira.project_key in config.toml and that the token's user can see the board.",
            )
        try:
            board_id = config.jira_board_id
        except ConfigError as exc:
            listing = ", ".join(f"{b['id']}={b['name']}" for b in boards[:5])
            return _check("jira", FAIL, str(exc), f"Available boards: {listing}")

        names = {b["id"]: b["name"] for b in boards}
        if board_id not in names:
            listing = ", ".join(f"{b['id']}={b['name']}" for b in boards[:5])
            return _check(
                "jira",
                FAIL,
                f"board {board_id} is not a board on {config.jira_project_key}",
                f"Set jira.board_id to one of: {listing}",
            )

        active = jira.active_sprint()
        sprint = f"active sprint '{active.name}'" if active else "no active sprint"
        return _check("jira", OK, f"board {board_id} '{names[board_id]}'; {sprint}")
    except ConfigError as exc:
        return _check("jira", FAIL, str(exc))
    except Exception as exc:
        return _check("jira", FAIL, str(exc), "Check jira.* in config.toml and ATLASSIAN_* in .env.")


def _probe_gitlab(config: Any) -> dict[str, Any]:
    try:
        from .gitlab import GitLabClient

        client = GitLabClient(config)
        me = client.http.get("/user")
        detail = f"authenticated as @{me.get('username', '?')} on {config.gitlab_url}"

        if not config.gitlab_default_project:
            return _check(
                "gitlab",
                OK,
                f"{detail}; no default project set",
                "Set gitlab.default_project in config.toml to skip passing it every time.",
            )
        project = client.get_project()
        return _check("gitlab", OK, f"{detail}; project {project['path']}")
    except ConfigError as exc:
        return _check("gitlab", FAIL, str(exc))
    except Exception as exc:
        return _check(
            "gitlab",
            FAIL,
            str(exc),
            "Check gitlab.url and gitlab.default_project in config.toml, and that GITLAB_TOKEN "
            "has the 'api' scope.",
        )


def _probe_vault(config: Any) -> dict[str, Any]:
    try:
        from .vault import Vault

        vault = Vault(config=config)
        stats = vault.stats()
        return _check("vault", OK, f"{stats['total_notes']} notes at {stats['path']}")
    except Exception as exc:
        return _check("vault", FAIL, str(exc), "Check vault.path in config.toml.")


def _summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    failures = [r for r in results if r["status"] == FAIL]
    return {
        "ok": not failures,
        "passed": sum(1 for r in results if r["status"] == OK),
        "failed": len(failures),
        "skipped": sum(1 for r in results if r["status"] == SKIP),
        "checks": results,
    }


def format_report(report: dict[str, Any]) -> str:
    symbols = {OK: "[ok]  ", FAIL: "[FAIL]", SKIP: "[--]  "}
    lines = ["", "donnyt doctor", "=" * 60]
    for check in report["checks"]:
        lines.append(f"{symbols[check['status']]} {check['check']:<16} {check['detail']}")
        if check.get("fix"):
            lines.append(f"         -> {check['fix']}")
    lines.append("=" * 60)
    verdict = "All good." if report["ok"] else f"{report['failed']} check(s) need attention."
    lines.append(f"{report['passed']} passed, {report['failed']} failed, {report['skipped']} skipped. {verdict}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    report = run_checks()
    print(format_report(report))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
