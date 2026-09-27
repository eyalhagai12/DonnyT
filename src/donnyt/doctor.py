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
    except SystemExit:
        # Not a failure: without mcp the CLI is the whole toolkit.
        results.append(
            _check(
                "mcp_package",
                SKIP,
                "not installed -- CLI-only mode; every tool is `python -m donnyt.cli <command>` "
                "(see `donnyt tools`)",
                "To enable the MCP server, re-run the installer with -IndexUrl / --index-url "
                "pointing at an internal package mirror, or ship a matching vendor/wheels "
                "bundle (INSTALL.md step 3).",
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
    results.append(_probe_atlassian(config))

    # -- live connectivity -------------------------------------------------
    results.append(_probe_confluence(config))
    results.append(_probe_jira(config))
    results.append(_probe_gitlab(config))
    results.append(_probe_vault(config))
    results.append(_probe_ui(config))

    return _summarize(results)


def _probe_atlassian(config: Any) -> dict[str, Any]:
    """Which Atlassian flavour and auth scheme are in effect -- the two settings
    most likely to be wrong on a self-hosted install."""
    try:
        deployment = config.atlassian_deployment
        setting = str((config.raw.get("atlassian") or {}).get("deployment") or "auto")
        scheme = config.atlassian_headers("jira")["Authorization"].split()[0].lower()
        auth = "personal access token" if scheme == "bearer" else "basic (user + token)"
        detail = (
            f"{deployment} ({'auto-detected' if setting == 'auto' else 'set'}); "
            f"jira {config.jira_url}; confluence {config.confluence_url}; auth {auth}"
        )
        return _check("atlassian", OK, detail)
    except ConfigError as exc:
        return _check("atlassian", FAIL, str(exc))


def _probe_confluence(config: Any) -> dict[str, Any]:
    try:
        from .confluence import ConfluenceClient

        client = ConfluenceClient(config)
        me = client.http.get("/rest/api/user/current")
        detail = f"authenticated as {me.get('displayName') or me.get('email') or 'unknown'}"

        # The PRD template is optional: report it, never fail on it.
        try:
            prd = client.get_template("prd")
            detail += f"; PRD template '{prd.title}' (id {prd.id})"
        except Exception:
            detail += "; no PRD template (optional: confluence.prd_template_page_id)"
        return _check("confluence", OK, detail)
    except ConfigError as exc:
        return _check("confluence", FAIL, str(exc))
    except Exception as exc:
        return _check(
            "confluence",
            FAIL,
            str(exc),
            f"Check the Confluence URL ({_safe(lambda: config.confluence_url)}) and the "
            "credentials in .env. A 404 usually means the wrong atlassian.deployment or a "
            "missing context path -- set atlassian.confluence_url to the address you open "
            "Confluence at in a browser (e.g. https://wiki.corp or https://corp/confluence). "
            "Behind a proxy set HTTPS_PROXY; if TLS is intercepted set DONNYT_CA_BUNDLE.",
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
        detail = f"board {board_id} '{names[board_id]}'; {sprint}"

        # The story points field id differs per site, and a wrong one fails
        # silently -- every issue just reads as unestimated.
        fields = {f["id"]: f["name"] for f in jira.fields()}
        points = config.story_points_field
        if points not in fields:
            guesses = [
                f"{fid} ({name})" for fid, name in fields.items()
                if "story point" in name.lower() or "estimate" in name.lower()
            ]
            return _check(
                "jira",
                FAIL,
                f"{detail}; story points field {points!r} does not exist on this site",
                "Set jira.story_points_field in config.toml"
                + (f" -- likely one of: {', '.join(guesses[:4])}" if guesses else "")
                + ".",
            )
        return _check("jira", OK, f"{detail}; points field {points} ({fields[points]})")
    except ConfigError as exc:
        return _check("jira", FAIL, str(exc))
    except Exception as exc:
        if "HTTP 403" in str(exc) and _jira_software_unlicensed(config):
            return _check(
                "jira",
                FAIL,
                str(exc),
                "Jira Software's licence is invalid or expired: sign-in still works, but every "
                "board and sprint call is refused. An admin renews it under Administration -> "
                "Applications -> Versions & licenses.",
            )
        return _check(
            "jira",
            FAIL,
            str(exc),
            f"Check the Jira URL ({_safe(lambda: config.jira_url)}), jira.* in config.toml and "
            "the credentials in .env. A 404 on /rest/api/3 means this is Data Center: set "
            "atlassian.deployment = \"datacenter\".",
        )


def _jira_software_unlicensed(config: Any) -> bool:
    """True when Data Center says Jira Software's licence is not valid.

    An expired licence looks like a permissions problem (HTTP 403 on the agile
    API) while basic sign-in keeps working, which sends people hunting in the
    wrong place. Unknown -- no such endpoint, e.g. on Cloud -- is False.
    """
    try:
        from .jira import JiraClient

        # The plugin API answers 406 to a plain application/json Accept.
        data = JiraClient(config).http.get(
            "/rest/plugins/applications/1.0/installed/jira-software/license",
            headers={"Accept": "application/vnd.atl.plugins+json, application/json"},
        )
        return isinstance(data, dict) and data.get("valid") is False
    except Exception:
        return False


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


def _probe_ui(config: Any) -> dict[str, Any]:
    """UI mockups are optional: report what is there, never fail."""
    from .ui import style_profile

    profile = style_profile(config)
    if not profile["browser"]:
        return _check(
            "ui_mockups", SKIP, "no Edge/Chrome found; /ui-mock cannot render",
            "Install Edge or Chrome, or set ui.browser in config.toml (INSTALL.md, 'UI mockups').",
        )
    shots = len(profile["screenshots"])
    detail = f"browser {profile['browser']}; {shots} reference screenshot{'s' * (shots != 1)}"
    if profile["notes"]:
        detail += " + style.md"
    return _check("ui_mockups", OK, detail)


def _safe(get: Any) -> str:
    try:
        return str(get())
    except Exception:
        return "unset"


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
