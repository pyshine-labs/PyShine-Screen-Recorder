#!/usr/bin/env python3
"""
Build MSIX package for Screen Recorder.

Prerequisites:
  1. Build the PyInstaller executable first:  python scripts/build_windows.py
  2. Windows SDK 10.0 must be installed (for MakeAppx.exe)

For Microsoft Store submission:
  1. Go to https://partner.microsoft.com/dashboard and register your app
  2. Copy the Identity Name and Publisher from "App identity" section
  3. Update AppxManifest.xml with those values
  4. Run this script to build the .msix
  5. Upload the .msix to Partner Center
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent.parent
MSIX_DIR = PROJECT_ROOT / "installer" / "msix"
DIST_DIR = PROJECT_ROOT / "dist"
STAGING_DIR = MSIX_DIR / "staging"
OUTPUT_DIR = PROJECT_ROOT / "installer" / "output"
EXE_PATH = DIST_DIR / "ScreenRecorder.exe"
MANIFEST_PATH = MSIX_DIR / "AppxManifest.xml"
ASSETS_DIR = MSIX_DIR / "Assets"

# Windows SDK
SDK_BASE = r"C:\Program Files (x86)\Windows Kits\10\bin"
MAKEAPPX = None

def find_makeappx():
    """Find MakeAppx.exe in Windows SDK."""
    global MAKEAPPX
    if not Path(SDK_BASE).exists():
        return None
    # Find the latest SDK version
    versions = sorted(Path(SDK_BASE).iterdir(), reverse=True)
    for version_dir in versions:
        candidate = version_dir / "x64" / "makeappx.exe"
        if candidate.exists():
            MAKEAPPX = str(candidate)
            return MAKEAPPX
    return None

def stage_files():
    """Copy all necessary files to the MSIX staging directory."""
    print("[1/4] Staging files...")
    
    # Clean staging dir
    if STAGING_DIR.exists():
        shutil.rmtree(STAGING_DIR)
    STAGING_DIR.mkdir(parents=True)
    
    # Copy executable
    if not EXE_PATH.exists():
        print(f"  ERROR: {EXE_PATH} not found!")
        print(f"  Build it first with: python scripts/build_windows.py")
        return False
    
    shutil.copy2(EXE_PATH, STAGING_DIR / "ScreenRecorder.exe")
    print(f"  Copied ScreenRecorder.exe ({EXE_PATH.stat().st_size / 1024 / 1024:.1f} MB)")
    
    # Copy manifest
    if not MANIFEST_PATH.exists():
        print(f"  ERROR: {MANIFEST_PATH} not found!")
        return False
    shutil.copy2(MANIFEST_PATH, STAGING_DIR / "AppxManifest.xml")
    print(f"  Copied AppxManifest.xml")
    
    # Copy Assets directory
    staging_assets = STAGING_DIR / "Assets"
    shutil.copytree(ASSETS_DIR, staging_assets)
    asset_count = sum(1 for f in staging_assets.rglob("*") if f.is_file())
    print(f"  Copied Assets ({asset_count} files)")
    
    return True

def build_msix():
    """Build the MSIX package using MakeAppx.exe."""
    print("\n[2/4] Building MSIX package...")
    
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / "ScreenRecorder.msix"
    
    if output_path.exists():
        output_path.unlink()
    
    cmd = [
        MAKEAPPX,
        "pack",
        "/d", str(STAGING_DIR),
        "/p", str(output_path),
        "/o",  # Overwrite
        "/v",  # Verbose
    ]
    
    print(f"  Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"  MakeAppx failed with code {result.returncode}")
        print(f"  stderr: {result.stderr}")
        print(f"  stdout: {result.stdout}")
        return False
    
    if output_path.exists():
        size_mb = output_path.stat().st_size / 1024 / 1024
        print(f"  SUCCESS: {output_path} ({size_mb:.1f} MB)")
        return True
    else:
        print("  ERROR: Output file was not created")
        return False

def create_mapping_file():
    """Create a mapping file for MakeAppx (alternative packing method)."""
    mapping_path = MSIX_DIR / "mapping.txt"
    with open(mapping_path, "w") as f:
        f.write("[Files]\n")
        f.write(f'"{STAGING_DIR / "ScreenRecorder.exe"}" "ScreenRecorder.exe"\n')
        f.write(f'"{STAGING_DIR / "AppxManifest.xml"}" "AppxManifest.xml"\n')
        for asset in ASSETS_DIR.rglob("*"):
            if asset.is_file():
                rel = asset.relative_to(ASSETS_DIR)
                f.write(f'"{asset}" "Assets\\{rel}"\n')
    return mapping_path

def verify_manifest():
    """Check that manifest doesn't contain placeholder values."""
    print("\n[3/4] Verifying manifest...")
    manifest_text = MANIFEST_PATH.read_text(encoding="utf-8")
    
    issues = []
    if "REPLACE_WITH_PARTNER_CENTER" in manifest_text:
        issues.append(
            "AppxManifest.xml still contains REPLACE_WITH_PARTNER_CENTER placeholders.\n"
            "  For Microsoft Store submission:\n"
            "    1. Go to https://partner.microsoft.com/dashboard\n"
            "    2. Create a new app and reserve the name 'Screen Recorder'\n"
            "    3. Go to 'Product management' > 'App identity'\n"
            "    4. Copy the Package/Identity/Name and Publisher values\n"
            "    5. Update installer/msix/AppxManifest.xml with those values\n"
            "    6. Re-run this script"
        )
    
    if issues:
        for issue in issues:
            print(f"  WARNING: {issue}")
        return False
    
    print("  Manifest looks good (no placeholder values)")
    return True

def cleanup():
    """Clean up staging directory."""
    print("\n[4/4] Cleaning up...")
    if STAGING_DIR.exists():
        shutil.rmtree(STAGING_DIR)
        print(f"  Removed staging directory")

def main():
    print("=" * 60)
    print("  Screen Recorder — MSIX Package Builder")
    print("=" * 60)
    print()
    
    # Find MakeAppx
    if not find_makeappx():
        print("ERROR: MakeAppx.exe not found!")
        print("  Install Windows SDK from: https://developer.microsoft.com/en-us/windows/downloads/windows-sdk/")
        sys.exit(1)
    print(f"Using MakeAppx: {MAKEAPPX}")
    print()
    
    # Check exe exists
    if not EXE_PATH.exists():
        print(f"ERROR: {EXE_PATH} not found.")
        print(f"  Build the executable first: python scripts/build_windows.py")
        sys.exit(1)
    
    # Stage files
    if not stage_files():
        sys.exit(1)
    
    # Verify manifest
    manifest_ok = verify_manifest()
    
    # Build MSIX
    if not build_msix():
        sys.exit(1)
    
    # Cleanup
    cleanup()
    
    print("\n" + "=" * 60)
    print("  MSIX BUILD COMPLETE")
    print(f"  Output: {OUTPUT_DIR / 'ScreenRecorder.msix'}")
    print("=" * 60)
    
    if not manifest_ok:
        print("\n  NOTE: The package was built but contains placeholder identity")
        print("  values. It will NOT pass Microsoft Store validation until you")
        print("  update AppxManifest.xml with your Partner Center identity.")
        print("\n  For local sideload testing, you can sign the package with:")
        print("    signtool sign /a /fd SHA256 installer/output/ScreenRecorder.msix")

if __name__ == "__main__":
    main()
