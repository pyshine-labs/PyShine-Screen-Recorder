#!/usr/bin/env python3
"""
Windows build script for Screen Recorder application.

Automates the PyInstaller build process:
  1. Checks / installs PyInstaller
  2. Cleans previous build artifacts
  3. Runs PyInstaller with the spec file
  4. Verifies the output executable exists

Usage:
    python scripts/build_windows.py
"""

import shutil
import subprocess
import sys
from pathlib import Path

# Project root directory (one level up from this script)
PROJECT_ROOT = Path(__file__).parent.parent
SPEC_FILE = PROJECT_ROOT / "screen_recorder.spec"
DIST_DIR = PROJECT_ROOT / "dist"
BUILD_DIR = PROJECT_ROOT / "build"
EXPECTED_EXE = DIST_DIR / "ScreenRecorder.exe"


def print_banner() -> None:
    """Print a build banner with project name and version."""
    # Read version from pyproject.toml
    version = "unknown"
    pyproject_path = PROJECT_ROOT / "pyproject.toml"
    if pyproject_path.exists():
        for line in pyproject_path.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("version"):
                version = line.split("=")[1].strip().strip('"').strip("'")
                break

    print()
    print("=" * 60)
    print(f"  Screen Recorder — Windows Build")
    print(f"  Version: {version}")
    print("=" * 60)
    print()


def check_pyinstaller() -> None:
    """Ensure PyInstaller is installed; install it if missing."""
    print("[1/4] Checking PyInstaller...")
    try:
        import PyInstaller  # noqa: F401
        print(f"  ✓ PyInstaller {PyInstaller.__version__} found")
    except ImportError:
        print("  PyInstaller not found — installing...")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "pyinstaller"],
        )
        print("  ✓ PyInstaller installed")


def clean_build_artifacts() -> None:
    """Remove previous build/ and dist/ directories."""
    print("[2/4] Cleaning previous build artifacts...")
    for directory in (BUILD_DIR, DIST_DIR):
        if directory.exists():
            shutil.rmtree(directory)
            print(f"  ✓ Removed {directory}")
        else:
            print(f"  — {directory} does not exist, skipping")


def run_pyinstaller() -> None:
    """Run PyInstaller with the spec file."""
    print("[3/4] Running PyInstaller...")
    if not SPEC_FILE.exists():
        print(f"  ✗ Spec file not found: {SPEC_FILE}")
        sys.exit(1)

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        str(SPEC_FILE),
        "--noconfirm",
        "--clean",
    ]
    print(f"  Command: {' '.join(cmd)}")
    subprocess.check_call(cmd, cwd=str(PROJECT_ROOT))
    print("  ✓ PyInstaller build completed")


def verify_output() -> None:
    """Verify the built executable exists."""
    print("[4/4] Verifying output...")
    if EXPECTED_EXE.exists():
        size_mb = EXPECTED_EXE.stat().st_size / (1024 * 1024)
        print(f"  ✓ Found: {EXPECTED_EXE} ({size_mb:.1f} MB)")
    else:
        print(f"  ✗ Expected executable not found: {EXPECTED_EXE}")
        sys.exit(1)


def main() -> None:
    """Run the full build pipeline."""
    try:
        print_banner()
        check_pyinstaller()
        clean_build_artifacts()
        run_pyinstaller()
        verify_output()

        print()
        print("=" * 60)
        print("  BUILD SUCCESSFUL")
        print(f"  Output: {EXPECTED_EXE.parent}")
        print("=" * 60)
        print()
    except KeyboardInterrupt:
        print("\n\nBuild interrupted by user.")
        sys.exit(1)
    except subprocess.CalledProcessError as exc:
        print(f"\n✗ Build failed: command exited with code {exc.returncode}")
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001
        print(f"\n✗ Build failed: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()