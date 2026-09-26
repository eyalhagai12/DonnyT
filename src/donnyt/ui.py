"""UI mockups: capture the look of a running system and render HTML mocks to PNG.

Everything goes through a Chromium browser that is already installed -- Edge
ships with Windows, Chrome or Chromium elsewhere -- run headless from the
command line. No browser automation library, so nothing to bundle for an
isolated network.

Two browser profiles are used, both under the repo root:

* ``.donnyt/browser-profile`` -- persistent. ``login`` opens it visibly so the
  user can sign in to an internal app once; ``capture`` reuses it headless, so
  screenshots are taken logged in.
* a throwaway profile per ``render`` call, with all network access blocked, so
  a mock cannot quietly depend on a CDN or web font the isolated host lacks.
"""

from __future__ import annotations

import os
import shutil
import struct
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import Config, load_config

# Enough for a JS-heavy internal app to fetch its data and paint.
_VIRTUAL_TIME_MS = 8000
_TIMEOUT_S = 120

_WINDOWS_CANDIDATES = [
    r"{PROGRAMFILES(X86)}\Microsoft\Edge\Application\msedge.exe",
    r"{PROGRAMFILES}\Microsoft\Edge\Application\msedge.exe",
    r"{LOCALAPPDATA}\Microsoft\Edge\Application\msedge.exe",
    r"{PROGRAMFILES}\Google\Chrome\Application\chrome.exe",
    r"{PROGRAMFILES(X86)}\Google\Chrome\Application\chrome.exe",
    r"{LOCALAPPDATA}\Google\Chrome\Application\chrome.exe",
]
_MAC_CANDIDATES = [
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
]
_PATH_NAMES = [
    "msedge", "microsoft-edge", "microsoft-edge-stable",
    "google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome",
]


class UIError(RuntimeError):
    """A mockup operation failed in a way the user can fix."""


@dataclass
class Screenshot:
    path: Path
    width: int
    height: int

    def as_dict(self) -> dict[str, Any]:
        return {"path": str(self.path), "name": self.path.stem, "width": self.width, "height": self.height}


def _family(candidate: str) -> str:
    """Which browser a candidate path is, for ``ui.browser = "chrome"`` and default-first ordering."""
    low = candidate.lower()
    if "edge" in low:
        return "edge"
    if "chromium" in low:
        return "chromium"
    return "chrome"


def _windows_default_family() -> str:
    """'chrome' or 'edge' when that is the user's default browser on Windows, else ''."""
    try:
        import winreg

        key = r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as handle:
            prog_id = str(winreg.QueryValueEx(handle, "ProgId")[0]).lower()
    except OSError:
        return ""
    if prog_id.startswith("chrome"):
        return "chrome"
    if prog_id.startswith("msedge"):
        return "edge"
    return ""


def find_browser(config: Config | None = None) -> Path:
    """The browser executable.

    ``ui.browser`` may be a path, or ``"chrome"`` / ``"edge"`` / ``"chromium"``
    to pick that browser wherever it is installed. When it is empty, the
    user's default browser comes first if it is Chrome or Edge: Windows always
    has Edge, but where people use Chrome, Chrome is the browser the company's
    sign-in and certificates are set up for.
    """
    config = config or load_config()
    setting = config.ui_browser.strip()
    wanted = setting.lower() if setting.lower() in ("chrome", "edge", "chromium") else ""
    if setting and not wanted:
        path = Path(setting)
        if not path.is_file():
            raise UIError(f"ui.browser in config.toml points at {path}, which does not exist.")
        return path

    candidates: list[str] = []
    if sys.platform == "win32":
        env = {k: os.environ.get(k, "") for k in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")}
        # Skip a candidate whose base folder is unset rather than probe a relative path.
        candidates = [
            c.format_map(env) for c in _WINDOWS_CANDIDATES
            if env[c[1:c.index("}")]]
        ]
    elif sys.platform == "darwin":
        candidates = list(_MAC_CANDIDATES)
    candidates += [found for name in _PATH_NAMES if (found := shutil.which(name))]

    if wanted:
        candidates = [c for c in candidates if _family(c) == wanted]
    elif sys.platform == "win32" and (default := _windows_default_family()):
        candidates.sort(key=lambda c: _family(c) != default)  # stable sort: default browser first
    for candidate in candidates:
        if Path(candidate).is_file():
            return Path(candidate)
    raise UIError(
        (f"ui.browser = {setting!r}, but no {wanted} installation was found. " if wanted
         else "No Edge, Chrome or Chromium found. ")
        + "Set ui.browser in config.toml to the browser executable (INSTALL.md, 'UI mockups')."
    )


def png_size(path: Path) -> tuple[int, int]:
    """Width and height from a PNG header; (0, 0) for anything else."""
    with path.open("rb") as fh:
        head = fh.read(24)
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        return 0, 0
    width, height = struct.unpack(">II", head[16:24])
    return width, height


def style_profile(config: Config | None = None) -> dict[str, Any]:
    """What the toolkit knows about the system's look: notes plus reference screenshots."""
    config = config or load_config()
    style_dir = config.ui_style_dir
    notes_file = style_dir / "style.md"
    screens_dir = style_dir / "screens"
    shots = [
        Screenshot(p, *png_size(p))
        for p in sorted(screens_dir.glob("*"))
        if p.suffix.lower() in (".png", ".jpg", ".jpeg")
    ] if screens_dir.is_dir() else []
    try:
        browser: str | None = str(find_browser(config))
    except UIError:
        browser = None
    return {
        "style_dir": str(style_dir),
        "notes": notes_file.read_text(encoding="utf-8") if notes_file.is_file() else "",
        "screenshots": [s.as_dict() for s in shots],
        "browser": browser,
        "mocks_dir": str(config.ui_mocks_dir),
    }


def login(url: str, config: Config | None = None) -> dict[str, Any]:
    """Open a visible browser window on DonnyT's own profile, to sign in once."""
    config = config or load_config()
    browser = find_browser(config)
    profile = config.ui_profile_dir
    profile.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(
        [str(browser), f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check", url],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return {
        "browser": str(browser),
        "profile": str(profile),
        "pid": proc.pid,
        "next": (
            "Sign in in the window that opened -- tick 'Remember me' / 'Keep me signed in' "
            "if offered, since a plain session cookie is dropped when the window closes -- "
            "then CLOSE the window. ui_capture reuses that login."
        ),
    }


def _headless(browser: Path, profile: Path, url: str, out: Path, size: tuple[int, int],
              extra: list[str] | None = None) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    args = [
        str(browser),
        "--headless=new",
        "--disable-gpu",
        "--hide-scrollbars",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
        f"--user-data-dir={profile}",
        f"--window-size={size[0]},{size[1]}",
        f"--virtual-time-budget={_VIRTUAL_TIME_MS}",
        f"--screenshot={out}",
        *(extra or []),
        url,
    ]
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise UIError(f"The browser did not finish within {_TIMEOUT_S}s loading {url}.") from None
    if not out.is_file():
        tail = (result.stderr or "").strip().splitlines()[-3:]
        raise UIError(
            f"The browser produced no screenshot for {url}. If a ui_login window is still open, "
            "close it first -- the profile can only be used by one browser at a time."
            + (f"\nBrowser said: {' | '.join(tail)}" if tail else "")
        )


def capture(url: str, name: str, width: int = 0, height: int = 0,
            config: Config | None = None) -> dict[str, Any]:
    """Screenshot a page of the running system into the style folder, logged in."""
    config = config or load_config()
    size = (width or config.ui_size[0], height or config.ui_size[1])
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in name).strip("-") or "screen"
    out = config.ui_style_dir / "screens" / f"{safe}.png"
    config.ui_profile_dir.mkdir(parents=True, exist_ok=True)
    _headless(find_browser(config), config.ui_profile_dir, url, out, size)
    return Screenshot(out, *png_size(out)).as_dict()


def render(html_path: str, width: int = 0, height: int = 0,
           config: Config | None = None) -> dict[str, Any]:
    """Render a self-contained HTML mock to a PNG beside it, with the network blocked."""
    config = config or load_config()
    source = Path(html_path)
    if not source.is_absolute():
        source = (Path.cwd() / source) if (Path.cwd() / source).is_file() else config.root / source
    if not source.is_file():
        raise UIError(f"No such HTML file: {html_path}")
    size = (width or config.ui_size[0], height or config.ui_size[1])
    out = source.with_suffix(".png")
    with tempfile.TemporaryDirectory(prefix="donnyt-render-") as profile:
        _headless(
            find_browser(config), Path(profile), source.resolve().as_uri(), out, size,
            # Offline by construction: any http(s) fetch fails, as it would on the isolated host.
            extra=["--host-resolver-rules=MAP * ~NOTFOUND"],
        )
    return {"html": str(source), **Screenshot(out, *png_size(out)).as_dict()}
