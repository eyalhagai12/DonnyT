"""Build the offline install bundle.

Run this on a machine WITH internet access, before zipping the repo for the
isolated network. It downloads every wheel the isolated host will need into
vendor/wheels/, so install.ps1 / install.sh can run with --no-index.

Only the ``mcp`` dependency tree is bundled. donnyt itself is never installed
as a package -- it always runs from src/ -- so editing this repo takes effect
immediately, with no reinstall and no build backend needed offline.

    python scripts/build_offline_bundle.py

Wheels are platform-specific. If the isolated host runs a different OS or
Python version than this machine, say so:

    python scripts/build_offline_bundle.py --platform win_amd64 --python-version 3.11
    python scripts/build_offline_bundle.py --platform manylinux2014_x86_64 --python-version 3.11

Then prove it works with --check, which installs the bundle offline in a
throwaway virtual environment.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WHEELS = ROOT / "vendor" / "wheels"


def run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
    print(f"  $ {' '.join(args)}")
    return subprocess.run(args, text=True, **kwargs)  # type: ignore[arg-type]


def build(platform: str | None, python_version: str | None, clean: bool) -> int:
    if clean and WHEELS.exists():
        for wheel in WHEELS.glob("*.whl"):
            wheel.unlink()
        print(f"Cleared existing wheels in {WHEELS}")

    WHEELS.mkdir(parents=True, exist_ok=True)

    print("\n[1/2] Downloading the mcp dependency tree")
    download = [sys.executable, "-m", "pip", "download", "--dest", str(WHEELS), "mcp>=1.2"]
    if platform or python_version:
        # Targeting another platform means pip cannot build sdists, so insist
        # on prebuilt wheels rather than silently producing an unusable bundle.
        download.append("--only-binary=:all:")
        if platform:
            download += ["--platform", platform]
        if python_version:
            download += ["--python-version", python_version]

    if run(download).returncode != 0:
        print(
            "\nFAILED to download dependencies.\n"
            "If this was a --platform build, some package may not publish a wheel for that "
            "target. Build the bundle on a machine matching the isolated host instead.",
            file=sys.stderr,
        )
        return 1

    print("\n[2/2] Writing the manifest")
    packages = sorted(p.name for p in WHEELS.iterdir() if p.suffix in {".whl", ".gz"})
    (WHEELS / "MANIFEST.txt").write_text(
        "\n".join(
            [
                "# donnyt offline bundle",
                f"# built:           {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
                f"# builder python:  {sys.version.split()[0]} on {sys.platform}",
                f"# target platform: {platform or 'same as builder'}",
                f"# target python:   {python_version or 'same as builder'}",
                f"# packages:        {len(packages)}",
                "",
                *packages,
                "",
            ]
        ),
        encoding="utf-8",
    )

    size_mb = sum(p.stat().st_size for p in WHEELS.iterdir() if p.is_file()) / 1_048_576
    print(f"\nBundle ready: {len(packages)} packages, {size_mb:.1f} MB in {WHEELS}")
    print("Verify with:  python scripts/build_offline_bundle.py --check")
    print("The repo is then safe to zip and carry across. See INSTALL.md.")
    return 0


def check() -> int:
    """Prove the bundle installs with no network, in a throwaway venv."""
    print("Verifying the bundle resolves with --no-index...")
    with tempfile.TemporaryDirectory() as tmp:
        venv = Path(tmp) / "venv"
        if run([sys.executable, "-m", "venv", str(venv)]).returncode != 0:
            return 1

        python = venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        result = run(
            [str(python), "-m", "pip", "install", "--no-index", "--find-links", str(WHEELS), "mcp"],
            capture_output=True,
        )
        if result.returncode != 0:
            print("\nBUNDLE INCOMPLETE:\n" + (result.stderr or "")[-2000:], file=sys.stderr)
            return 1

        # donnyt runs from src/, exactly as the installer wires it up.
        verify = run(
            [
                str(python),
                "-c",
                f"import sys; sys.path.insert(0, r'{ROOT / 'src'}'); "
                "import donnyt, mcp; print('offline bundle OK; donnyt', donnyt.__version__)",
            ],
            capture_output=True,
        )
        print((verify.stdout or "").strip() or (verify.stderr or "").strip())
        return verify.returncode


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--platform", help="Target platform tag, e.g. win_amd64, manylinux2014_x86_64")
    parser.add_argument("--python-version", help="Target Python, e.g. 3.11")
    parser.add_argument("--clean", action="store_true", help="Remove existing wheels first")
    parser.add_argument("--check", action="store_true", help="Verify the bundle installs offline")
    args = parser.parse_args()

    return check() if args.check else build(args.platform, args.python_version, args.clean)


if __name__ == "__main__":
    raise SystemExit(main())
