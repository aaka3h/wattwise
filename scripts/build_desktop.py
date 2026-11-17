#!/usr/bin/env python3
"""Cross-platform standalone desktop app builder for WattWise (Linux, Windows, macOS M-series & Intel)."""

from __future__ import annotations

import platform
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
ENTRY = ROOT / "src" / "wattwise" / "__main__.py"


def main() -> int:
    if shutil.which("pyinstaller") is None:
        print("PyInstaller is not installed. Install it first with:")
        print("  pip install pyinstaller")
        return 1

    sys_name = platform.system().lower()
    arch = platform.machine().lower()
    print(f"Building standalone WattWise desktop application for {sys_name} ({arch})...")

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--name",
        "WattWise",
        "--paths",
        str(ROOT / "src"),
    ]

    if sys_name == "windows":
        cmd.append("--onefile")
    elif sys_name == "darwin":
        # Produces dist/WattWise.app native macOS bundle (Apple Silicon arm64 or Intel x86_64)
        cmd.extend(["--osx-bundle-identifier", "io.wattwise.desktop"])
    else:
        cmd.append("--onefile")

    cmd.append(str(ENTRY))
    res = subprocess.run(cmd, cwd=str(ROOT), check=False)
    if res.returncode == 0:
        dist_dir = ROOT / "dist"
        print(f"\nBuild succeeded! Artifacts located in: {dist_dir}")
    return res.returncode


if __name__ == "__main__":
    raise SystemExit(main())
