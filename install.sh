#!/usr/bin/env bash
# Install DonnyT on this machine. Works with no internet access.
#
# Creates a virtual environment, installs the one optional dependency ('mcp'),
# seeds .env and config.toml, generates .mcp.json for Claude Code, and runs the
# doctor. Safe to re-run.
#
# 'mcp' is looked for in vendor/wheels, then in a package index (--index-url,
# DONNYT_INDEX_URL, or pip's own config). If neither has it the install still
# succeeds in CLI-only mode: every tool works as `python -m donnyt.cli ...`.
#
#   ./install.sh                         use whatever is available
#   ./install.sh --index-url URL         install mcp from an internal mirror
#   ./install.sh --source bundle|index   use only that source; fail if it fails
#   ./install.sh --source none           skip mcp, CLI-only
#   ./install.sh --online                allow PyPI (connected machines only)
#   ./install.sh --force                 rebuild the virtual environment

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$ROOT/.venv"
WHEELS="$ROOT/vendor/wheels"

SOURCE="auto"
INDEX_URL="${DONNYT_INDEX_URL:-}"
MCP_SPEC="mcp>=1.2"
FORCE=0
PYTHON_BIN=""

while [ $# -gt 0 ]; do
    case "$1" in
        --source)    SOURCE="$2"; shift ;;
        --index-url) INDEX_URL="$2"; shift ;;
        --mcp-spec)  MCP_SPEC="$2"; shift ;;
        --online)    SOURCE="index"; INDEX_URL="" ;;
        --force)     FORCE=1 ;;
        --python)    PYTHON_BIN="$2"; shift ;;
        -h|--help) sed -n '2,19p' "$0"; exit 0 ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
    shift
done

case "$SOURCE" in
    auto|bundle|index|none) ;;
    *) echo "--source must be auto, bundle, index or none (got '$SOURCE')" >&2; exit 1 ;;
esac

C_CYAN=$'\033[36m'; C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'; C_RED=$'\033[31m'; C_OFF=$'\033[0m'
step() { printf '\n%s[%s] %s%s\n' "$C_CYAN" "$1" "$2" "$C_OFF"; }
ok()   { printf '      %s%s%s\n' "$C_GREEN"  "$1" "$C_OFF"; }
warn() { printf '      %s%s%s\n' "$C_YELLOW" "$1" "$C_OFF"; }
err()  { printf '      %s%s%s\n' "$C_RED"    "$1" "$C_OFF"; }

printf '\n=== DonnyT install ===\nRepo: %s\n' "$ROOT"

# --- 1. Find a usable Python ------------------------------------------------
step 1 "Locating Python 3.11 or newer"

find_python() {
    local candidates=("$@")
    for candidate in "${candidates[@]}"; do
        command -v "$candidate" >/dev/null 2>&1 || continue
        if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)' 2>/dev/null; then
            echo "$candidate"
            return 0
        fi
    done
    return 1
}

if [ -n "$PYTHON_BIN" ]; then
    PY="$PYTHON_BIN"
elif ! PY="$(find_python python3.13 python3.12 python3.11 python3 python)"; then
    err "No Python 3.11+ found."
    err "Install Python 3.11 or newer, or point at it directly:"
    err "    ./install.sh --python /opt/python3.11/bin/python3"
    exit 1
fi
ok "Using $PY -> $("$PY" -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')"

# --- 2. Virtual environment -------------------------------------------------
step 2 "Creating the virtual environment"

VENV_PY="$VENV/bin/python"
if [ -x "$VENV_PY" ] && [ "$FORCE" -eq 0 ]; then
    ok ".venv already exists (use --force to rebuild)"
else
    [ "$FORCE" -eq 1 ] && rm -rf "$VENV"
    "$PY" -m venv "$VENV"
    ok "Created $VENV"
fi

# --- 3. Install dependencies ------------------------------------------------
step 3 "Installing the MCP dependency (optional)"

# donnyt itself is never installed as a package -- the .pth file below points
# at src/, so edits to this repo take effect with no reinstall. Only the MCP
# server's dependency needs installing, and even that is optional.
wheel_count=0
[ -d "$WHEELS" ] && wheel_count=$(find "$WHEELS" -name '*.whl' 2>/dev/null | wc -l | tr -d ' ')

install_from_bundle() {
    if [ "$wheel_count" -eq 0 ]; then
        warn "No offline bundle: vendor/wheels is empty."
        return 1
    fi
    ok "Trying the offline bundle ($wheel_count wheels in vendor/wheels)"
    if "$VENV_PY" -m pip install --quiet --disable-pip-version-check --no-index --find-links "$WHEELS" "$MCP_SPEC"; then
        return 0
    fi
    warn "The bundle does not fit this machine's Python/OS (see vendor/wheels/MANIFEST.txt)."
    return 1
}

install_from_index() {
    local args=(-m pip install --quiet --disable-pip-version-check --timeout 15 --retries 1)
    if [ -n "$INDEX_URL" ]; then
        ok "Trying package index $INDEX_URL"
        args+=(--index-url "$INDEX_URL")
        # Plain-http mirrors are common inside; pip refuses them unless trusted.
        case "$INDEX_URL" in
            http://*) host="${INDEX_URL#http://}"; args+=(--trusted-host "${host%%[/:]*}") ;;
        esac
    else
        ok "Trying pip's configured index (pip.conf / PIP_INDEX_URL, else PyPI)"
    fi
    if "$VENV_PY" "${args[@]}" "$MCP_SPEC"; then
        return 0
    fi
    warn "The package index did not provide '$MCP_SPEC'."
    return 1
}

mcp_ready=0
case "$SOURCE" in
    bundle) install_from_bundle && mcp_ready=1 ;;
    index)  install_from_index && mcp_ready=1 ;;
    auto)   { install_from_bundle || install_from_index; } && mcp_ready=1 ;;
    none)   ok "Skipped (--source none)" ;;
esac

if [ "$mcp_ready" -eq 1 ]; then
    ok "MCP dependency installed"
elif [ "$SOURCE" = "bundle" ] || [ "$SOURCE" = "index" ]; then
    err "Could not install '$MCP_SPEC' from the requested source ($SOURCE)."
    err "Re-run with --source auto to fall back to CLI-only mode, or see INSTALL.md step 3."
    exit 1
else
    warn "Continuing in CLI-only mode: every tool works as 'python -m donnyt.cli <command>'."
    warn "To add the MCP server later, re-run with --index-url <mirror>, or ship a"
    warn "vendor/wheels bundle built for this machine (INSTALL.md step A2)."
fi

# Put src/ on the interpreter's path so `python -m donnyt.cli` just works.
SITE_PACKAGES="$("$VENV_PY" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
if [ -d "$SITE_PACKAGES" ]; then
    printf '%s\n' "$ROOT/src" > "$SITE_PACKAGES/donnyt_src.pth"
    ok "Linked src/ into the virtual environment"
fi

# --- 4. Seed the config files ----------------------------------------------
step 4 "Seeding configuration files"

seed() {
    if [ -f "$ROOT/$2" ]; then
        ok "$2 already exists - left untouched"
    elif [ -f "$ROOT/$1" ]; then
        cp "$ROOT/$1" "$ROOT/$2"
        chmod 600 "$ROOT/$2" 2>/dev/null || true
        ok "Created $2 from $1 - YOU MUST EDIT THIS"
    fi
}
seed ".env.example" ".env"
seed "config.example.toml" "config.toml"

# --- 5. Generate .mcp.json --------------------------------------------------
step 5 "Registering the MCP server for Claude Code"

if [ "$mcp_ready" -eq 0 ]; then
    # A server entry that cannot start is worse than none: Claude Code would
    # report a broken server instead of the skills falling back to the CLI.
    rm -f "$ROOT/.mcp.json"
    warn "Skipped - no 'mcp' package. The skills will drive the CLI instead."
else
"$VENV_PY" - "$ROOT" "$VENV_PY" <<'PYEOF'
import json, sys
from pathlib import Path

root, venv_python = Path(sys.argv[1]), sys.argv[2]
# DONNYT_HOME pins the repo so the server finds .env and config.toml
# regardless of the directory Claude Code launches it from.
config = {"mcpServers": {"donnyt": {"command": venv_python,
                                    "args": ["-m", "donnyt.mcp_server"],
                                    "env": {"DONNYT_HOME": str(root)}}}}
(root / ".mcp.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
PYEOF
ok "Wrote .mcp.json pointing at $VENV_PY"
fi

# --- 6. Doctor --------------------------------------------------------------
step 6 "Running the doctor"

set +e
"$VENV_PY" -m donnyt.cli doctor
doctor_exit=$?
set -e

printf '\n=== Next steps ===\n'
if [ "$doctor_exit" -ne 0 ]; then
    echo "  1. Edit .env         - add your Atlassian and GitLab tokens   (INSTALL.md step 4)"
    echo "  2. Edit config.toml  - site URL, project key, board id, team  (INSTALL.md step 5)"
    echo "  3. Re-run:  ./.venv/bin/python -m donnyt.cli doctor"
    echo "  4. Open this folder in Claude Code and approve the 'donnyt' MCP server."
else
    printf '  %sEverything checks out.%s\n' "$C_GREEN" "$C_OFF"
    echo "  Open this folder in Claude Code, approve the 'donnyt' MCP server, then try:"
    printf '      %s/sprint-plan%s\n' "$C_CYAN" "$C_OFF"
fi
echo
exit "$doctor_exit"
