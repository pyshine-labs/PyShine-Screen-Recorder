# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for Screen Recorder application.

Build configuration:
  - Mode: onefile (single-file build)
  - Windowed: no console window
  - Entry point: screen_recorder.app:main
  - UAC admin: False (no elevation needed)
"""

import os
import sys
from pathlib import Path

block_cipher = None

# ---------------------------------------------------------------------------
# Helper: locate PyQt6 platform plugin (qwindows.dll)
# ---------------------------------------------------------------------------
def _find_qt_platform_plugin():
    """Locate the PyQt6 Qt platform plugin directory for Windows."""
    try:
        from PyQt6.QtCore import QLibraryInfo
        plugins_dir = QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath)
        platforms_dir = os.path.join(plugins_dir, "platforms")
        if os.path.isdir(platforms_dir):
            return [(os.path.join(platforms_dir, "qwindows.dll"), "PyQt6/Qt6/plugins/platforms")]
    except Exception:
        pass
    # Fallback: try to find via PyQt6 package path
    try:
        import PyQt6
        pyqt6_dir = os.path.dirname(PyQt6.__file__)
        candidate = os.path.join(pyqt6_dir, "Qt6", "plugins", "platforms", "qwindows.dll")
        if os.path.isfile(candidate):
            return [(candidate, "PyQt6/Qt6/plugins/platforms")]
        candidate = os.path.join(pyqt6_dir, "Qt", "plugins", "platforms", "qwindows.dll")
        if os.path.isfile(candidate):
            return [(candidate, "PyQt6/Qt/plugins/platforms")]
    except Exception:
        pass
    print("WARNING: Could not locate PyQt6 platform plugin (qwindows.dll). "
          "The build may not run correctly.")
    return []

# ---------------------------------------------------------------------------
# Data files
# ---------------------------------------------------------------------------
datas = []

# Application icons — only include if there are actual files (not just .gitkeep)
_icons_dir = os.path.join(os.path.dirname(os.path.abspath(SPECPATH)), "resources", "icons")
if os.path.isdir(_icons_dir):
    _icon_files = [f for f in os.listdir(_icons_dir) if not f.startswith(".")]
    if _icon_files:
        datas.append(("resources/icons/*", "resources/icons"))

# Package resources (if they exist under src/)
_src_res_dir = os.path.join(os.path.dirname(os.path.abspath(SPECPATH)), "src", "screen_recorder", "resources")
if os.path.isdir(_src_res_dir):
    _src_res_files = [f for f in os.listdir(_src_res_dir) if not f.startswith(".")]
    if _src_res_files:
        datas.append(("src/screen_recorder/resources/*", "screen_recorder/resources"))

# ---------------------------------------------------------------------------
# Binary files (Qt platform plugins)
# ---------------------------------------------------------------------------
binaries = _find_qt_platform_plugin()

# ---------------------------------------------------------------------------
# Icon file (only set if the .ico actually exists)
# ---------------------------------------------------------------------------
_app_icon = None
_app_ico_path = os.path.join(os.path.dirname(os.path.abspath(SPECPATH)), "resources", "icons", "app.ico")
if os.path.isfile(_app_ico_path):
    _app_icon = _app_ico_path

# ---------------------------------------------------------------------------
# Hidden imports
# ---------------------------------------------------------------------------
hiddenimports = [
    # Screen capture
    "mss", "mss.screenshot", "mss.base",
    # Video/audio encoding
    "av", "av.video", "av.audio", "av.codec", "av.container", "av.format", "av.stream",
    # Audio capture
    "sounddevice", "_sounddevice",
    "pyaudiowpatch", "pyaudiowpatch._pyaudiowpatch",
    # Numerics
    "numpy", "numpy._core",
    # Image processing
    "PIL", "PIL.Image", "PIL._tkinter_finder",
    # Qt framework
    "PyQt6", "PyQt6.QtCore", "PyQt6.QtGui", "PyQt6.QtWidgets", "PyQt6.sip",
    # Application modules
    "screen_recorder", "screen_recorder.audio", "screen_recorder.capture",
    "screen_recorder.encoding", "screen_recorder.gui", "screen_recorder.config",
    "screen_recorder.utils",
]

# ---------------------------------------------------------------------------
# Excluded modules (reduce bundle size)
# ---------------------------------------------------------------------------
excludes = [
    "tkinter", "_tkinter",
    "matplotlib", "mpl_toolkits",
    "scipy", "pandas",
    "pytest", "_pytest",
    "setuptools", "pip",
    "IPython", "jupyterlab",
    "notebook", "tornado",
]

# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------
a = Analysis(
    ["src/screen_recorder/__main__.py"],
    pathex=["src"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries + a.zipfiles + a.datas,
    [],
    name="ScreenRecorder",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # noconsole — no terminal window
    icon=_app_icon,  # None if app.ico is missing (uses default icon)
    uac_admin=False,  # no admin elevation needed
)