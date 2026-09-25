"""Build the offline install bundle.

Run this on a machine WITH internet access, before zipping the repo for the
isolated network. It downloads every wheel the isolated host will need into
vendor/wheels/, so install.ps1 / install.sh can run with --no-index.

Only the ``mcp`` dependency tree is bundled. donnyt itself is never installed
as a package -- it always runs from src/ -- so editing this repo takes effect
immediately, with no reinstall and no build backend needed offline.

    python scripts/build_offline_bundle.py

Wheels are platform-specific. When you do not know the isolated host's OS or
Python version, bundle for several -- pip picks the matching wheels at install
time, and pure-Python wheels are shared, so the cost is small:

    python scripts/build_offline_bundle.py --preset common
    python scripts/build_offline_bundle.py --target win_amd64:3.11 --target win_amd64:3.12

A target is PLATFORM[,PLATFORM...]:PYTHON_VERSION. Then prove it with --check,
which installs the bundle offline in a throwaway virtual environment, and
resolves it offline for every target recorded in the manifest.

The bundle is optional. If it does not fit the isolated host, the installer
falls back to an internal package index, and failing that to CLI-only mode.
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
MCP_SPEC = "mcp>=1.2"

# Linux wheels are published as manylinux2014 (glibc 2.17) or manylinux_2_28;
# accepting both covers RHEL/Rocky 8+ and Ubuntu 20.04+.
LINUX = "manylinux2014_x86_64,manylinux_2_28_x86_64"
VERSIONS = ("3.11", "3.12", "3.13")
PRESETS = {
    "windows": [f"win_amd64:{py}" for py in VERSIONS],
    "linux": [f"{LINUX}:{py}" for py in VERSIONS],
    "common": [f"{plat}:{py}" for plat in ("win_amd64", LINUX) for py in VERSIONS],
}


def run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
    print(f"  $ {' '.join(args)}")
    return subprocess.run(args, text=True, **kwargs)  # type: ignore[arg-type]


def parse_target(target: str) -> tuple[list[str], str]:
    platforms, sep, version = target.rpartition(":")
    if not sep or not platforms or not version:
        raise SystemExit(f"Bad target {target!r}: expected PLATFORM[,PLATFORM...]:PYTHON_VERSION")
    return platforms.split(","), version


def target_args(target: str) -> list[str]:
    """pip flags that make it resolve for ``target`` instead of this machine.

    Targeting another platform means pip cannot build sdists, so insist on
    prebuilt wheels rather than silently producing an unusable bundle.
    """
    platforms, version = parse_target(target)
    args = ["--only-binary=:all:", "--python-version", version]
    for plat in platforms:
        args += ["--platform", plat]
    return args


def build(targets: list[str], clean: bool) -> int:
    if clean and WHEELS.exists():
        for wheel in WHEELS.glob("*.whl"):
            wheel.unlink()
        print(f"Cleared existing wheels in {WHEELS}")

    WHEELS.mkdir(parents=True, exist_ok=True)

    # No targets means "this machine", which pip handles natively.
    plan = targets or [""]
    for n, target in enumerate(plan, 1):
        label = target or "this machine"
        print(f"\n[{n}/{len(plan)}] Downloading the mcp dependency tree for {label}")
        download = [sys.executable, "-m", "pip", "download", "--dest", str(WHEELS), MCP_SPEC]
        if target:
            download += target_args(target)
        if run(download).returncode != 0:
            print(
                f"\nFAILED to download dependencies for {label}.\n"
                "Some package may not publish a wheel for that target. Drop the target, or "
                "build the bundle on a machine matching the isolated host.",
                file=sys.stderr,
            )
            return 1

    print("\nWriting the manifest")
    packages = sorted(p.name for p in WHEELS.iterdir() if p.suffix in {".whl", ".gz"})
    here = f"{sys.platform}, Python {sys.version_info.major}.{sys.version_info.minor}"
    (WHEELS / "MANIFEST.txt").write_text(
        "\n".join(
            [
                "# donnyt offline bundle",
                f"# built:           {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
                f"# builder python:  {sys.version.split()[0]} on {sys.platform}",
                f"# requirement:     {MCP_SPEC}",
                f"# packages:        {len(packages)}",
                "# targets:",
                *(f"#   target {t}" for t in targets),
                *([f"#   the build machine only ({here})"] if not targets else []),
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


def manifest_targets() -> list[str]:
    manifest = WHEELS / "MANIFEST.txt"
    if not manifest.exists():
        return []
    prefix = "#   target "
    return [
        line[len(prefix):].strip()
        for line in manifest.read_text(encoding="utf-8").splitlines()
        if line.startswith(prefix)
    ]


def check() -> int:
    """Prove the bundle installs with no network, here and for every target."""
    print("Verifying the bundle installs on this machine with --no-index...")
    with tempfile.TemporaryDirectory() as tmp:
        venv = Path(tmp) / "venv"
        if run([sys.executable, "-m", "venv", str(venv)]).returncode != 0:
            return 1

        python = venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        result = run(
            [str(python), "-m", "pip", "install", "--no-index", "--find-links", str(WHEELS), MCP_SPEC],
            capture_output=True,
        )
        if result.returncode != 0:
            print("\nBUNDLE DOES NOT FIT THIS MACHINE:\n" + (result.stderr or "")[-2000:], file=sys.stderr)
            if not manifest_targets():
                return 1
            print("(continuing: checking the bundle's declared targets instead)\n")
        else:
            # donnyt runs from src/, exactly as the installer wires it up.
            verify = run(
                [
                    str(python),
                    "-c",
                    f"import sys; sys.path.insert(0, r'{ROOT / 'src'}'); "
                    "import donnyt, mcp; print('offline bundle OK here; donnyt', donnyt.__version__)",
                ],
                capture_output=True,
            )
            print((verify.stdout or "").strip() or (verify.stderr or "").strip())
            if verify.returncode != 0:
                return verify.returncode

        # Other targets cannot be installed here, but pip can prove their full
        # dependency tree resolves from the bundle alone.
        failed = 0
        for target in manifest_targets():
            result = run(
                [sys.executable, "-m", "pip", "download", "--no-index", "--find-links", str(WHEELS),
                 "--dest", str(Path(tmp) / "resolve"), MCP_SPEC, *target_args(target)],
                capture_output=True,
            )
            ok = result.returncode == 0
            print(f"  {'OK        ' if ok else 'INCOMPLETE'}  {target}")
            if not ok:
                failed += 1
                print((result.stderr or "")[-800:], file=sys.stderr)
        return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--target", action="append", default=[],
        help="PLATFORM[,PLATFORM...]:PYTHON_VERSION, e.g. win_amd64:3.11. Repeatable.",
    )
    parser.add_argument("--preset", choices=sorted(PRESETS), help="A ready-made set of targets.")
    parser.add_argument("--platform", help="Single target platform (shorthand for one --target).")
    parser.add_argument("--python-version", help="Single target Python (shorthand for one --target).")
    parser.add_argument("--clean", action="store_true", help="Remove existing wheels first")
    parser.add_argument("--check", action="store_true", help="Verify the bundle installs offline")
    args = parser.parse_args()

    if args.check:
        return check()

    targets = list(args.target)
    if args.preset:
        targets += PRESETS[args.preset]
    if args.platform or args.python_version:
        platform = args.platform or ("win_amd64" if sys.platform == "win32" else LINUX)
        version = args.python_version or f"{sys.version_info.major}.{sys.version_info.minor}"
        targets.append(f"{platform}:{version}")
    for target in targets:
        parse_target(target)
    return build(targets, args.clean)


if __name__ == "__main__":
    raise SystemExit(main())
