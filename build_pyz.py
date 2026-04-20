"""
Bundle the entire IO Analysis tool into a single portable .pyz file.
Uses Python's built-in zipapp module — no extra packages needed.

Usage:
    python build_pyz.py

Output:
    IO_Analysis.pyz   <- double-click or run with: python IO_Analysis.pyz
    IO_Analysis.bat   <- double-click launcher for Windows (wraps the .pyz)
"""

import zipapp
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
BUILD_DIR = ROOT / "_pyz_build"
OUT_PYZ = ROOT / "IO_Analysis.pyz"
OUT_BAT = ROOT / "IO_Analysis.bat"


def main():
    print("Building portable IO_Analysis.pyz ...")

    # Clean and recreate staging directory
    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)
    BUILD_DIR.mkdir()

    # Copy the package
    shutil.copytree(ROOT / "io_analysis", BUILD_DIR / "io_analysis")

    # Copy the GUI entry point as __main__.py
    shutil.copy(ROOT / "gui_launcher.py", BUILD_DIR / "__main__.py")

    # Build the .pyz
    if OUT_PYZ.exists():
        OUT_PYZ.unlink()

    zipapp.create_archive(
        source=str(BUILD_DIR),
        target=str(OUT_PYZ),
        interpreter=sys.executable,
    )

    # Clean up staging
    shutil.rmtree(BUILD_DIR)

    # Create a .bat wrapper so the .pyz can be double-clicked on Windows
    OUT_BAT.write_text(
        f'@echo off\n'
        f'cd /d "%~dp0"\n'
        f'python IO_Analysis.pyz %*\n'
        f'if errorlevel 1 pause\n',
        encoding="utf-8",
    )

    print(f"\nDone!")
    print(f"  Portable archive : {OUT_PYZ}")
    print(f"  Windows launcher : {OUT_BAT}")
    print()
    print("To distribute: copy IO_Analysis.pyz + IO_Analysis.bat to any machine")
    print("that has Python 3.9+ installed. Double-click IO_Analysis.bat to run.")


if __name__ == "__main__":
    main()
