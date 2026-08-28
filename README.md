# PyShine Screen Recorder

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux-lightgrey.svg)](https://github.com)
[![Latest Release](https://img.shields.io/badge/Release-v1.0.8-blue.svg)](https://github.com/pyshine-labs/PyShine-Screen-Recorder/releases)
[![Website](https://img.shields.io/badge/www-pyshine.com-6366f1.svg)](https://www.pyshine.com)

A professional, high-performance screen recording application built with PyQt6 and a native C++ recording engine. Features DXGI Desktop Duplication for GPU-accelerated screen capture, WASAPI audio capture, near-lossless H.264 encoding (CRF 1), box-filter downscaling (4K to 1080p), region crop capture, an animated on-screen recording boundary overlay, and a polished dark-themed UI.

## Demo Video

[![PyShine Screen Recorder Demo](https://img.youtube.com/vi/lYAzO1FVgvg/0.jpg)](https://youtube.com/shorts/lYAzO1FVgvg)

## Downloads

Download the latest version from the [GitHub Releases](https://github.com/pyshine-labs/PyShine-Screen-Recorder/releases) page:

- **Standalone EXE** — `ScreenRecorder.exe` — single-file executable, no installation required

## Features

- **Native C++ recording engine** — WASAPI audio capture and DXGI Desktop Duplication screen capture via native threads (no Python GIL interference)
- **100% A/V sync** — producer-consumer architecture decouples capture from writing; a dedicated writer thread maintains strict constant frame rate (CFR) by writing duplicate frames when the capture queue is empty, ensuring the video timeline never falls behind audio regardless of recording length
- **Near-lossless quality** — CRF 1 (visually lossless) H.264 encoding with `ultrafast` preset, universally playable High profile, yuv420p
- **1080p native resolution** — captures at full 1920×1080 with no resolution compromise; 4K monitors are downscaled to 1080p using area-averaging (2×2 box filter), the theoretically optimal method: no aliasing, no blurring, maximally sharp
- **Cached GPU staging texture** — staging texture created once and reused every frame, eliminating the per-frame allocation that caused stutter and freeze
- **Region selection** with professional overlay — 8 resize handles, drag-to-move, confirm/cancel buttons. Native C++ region crop captures only the selected area
- **Multi-monitor support** — select which display to capture
- **Microphone + system audio** — WASAPI capture with automatic fallback to system loopback when microphone is disabled
- **System tray icon** with recording controls (start/stop/pause/resume)
- **Animated recording boundary overlay** — dotted marching-ants border with a pulsing REC indicator, drawn outside the captured region so it never appears in the video
- **Professional dark-themed UI** — compact rectangular layout with 3-tier surface palette, indigo accents, circular icon buttons, horizontal stereo audio meter, and PyShine branding (logo + version + website link)
- **Help dialog** — press `F1` or click the `?` button for a quick reference of keyboard shortcuts and usage
- **Audio level meter** — real-time stereo RMS and peak monitoring from the native engine
- **Settings panel** — output directory, FPS (30/24), microphone toggle, system audio toggle
- **Live recording history** — delete recordings from the UI also removes the file from disk
- **Pause/resume support** during active recording
- **MP4 output** via FFmpeg with two-pass muxing
- **F9 hotkey** — start/stop recording with a single keypress

---

## Requirements

| Requirement | Minimum |
|---|---|
| Python | 3.10+ |
| Operating System | Windows 10+ (primary), Linux (partial) |
| RAM | 4 GB |
| CPU | Dual-core |
| GPU | Integrated graphics (DXGI Desktop Duplication) |

### Python Dependencies

| Package | Version | Purpose |
|---|---|---|
| PyQt6 | >= 6.5.0 | GUI framework |
| pyaudiowpatch | >= 0.2.12 | WASAPI loopback (system audio) |
| Pillow | >= 10.0.0 | Image processing |

---

## Installation

### Windows (Standalone EXE — Recommended)

1. Download **`ScreenRecorder.exe`** from the [Releases page](https://github.com/pyshine-labs/PyShine-Screen-Recorder/releases)
2. Run directly — no extraction or installation required

> **Note:** No Python installation required. Windows 10/11 (64-bit) supported.

### From Source (Developers)

```bash
# Clone the repository
git clone https://github.com/pyshine-labs/PyShine-Screen-Recorder.git
cd PyShine-Screen-Recorder

# Create a virtual environment (recommended)
python -m venv .venv
.venv\Scripts\activate

# Install the package in development mode
pip install -e .

# Or install dependencies directly
pip install -r requirements.txt
```

To run the application:

```bash
python -m screen_recorder
```

---

## Building from Source

### Prerequisites

- **Python** >= 3.10
- **PyInstaller**: `pip install pyinstaller`
- **Visual Studio 2022 Build Tools** (C++ workload) and CMake

### Build the Native C++ Recorder DLL

```bash
# Builds recorder.dll -> bin/Release/recorder.dll
native\build.bat
```

### Build the Portable EXE

```bash
python -m PyInstaller screen_recorder.spec --noconfirm
```

The output is located at `dist/ScreenRecorder.exe`.

---

## Usage

### Running the Application

```bash
python -m screen_recorder
```

### Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| `F9` | Start / Stop recording |
| `Ctrl+P` | Pause / Resume recording |
| `Ctrl+Q` | Quit application |
| `Esc` | Cancel region selection |

### Basic Workflow

1. **Launch** the application — the main window appears with controls.
2. **Select a capture source** — choose a display or draw a region using the overlay selector.
3. **Configure audio** — enable microphone and/or system audio in Settings.
4. **Start recording** — press `F9` or click the Record button.
5. **Stop recording** — press `F9` again. The MP4 file is saved to your output directory.

---

## Project Structure

```
PyShine-Screen-Recorder/
├── pyproject.toml                  # Project configuration (PEP 621)
├── requirements.txt                # Runtime dependencies
├── screen_recorder.spec            # PyInstaller build spec
├── README.md                       # This file
├── LICENSE                         # MIT License
│
├── native/                          # Native C++ recording engine
│   ├── CMakeLists.txt                # CMake build config
│   ├── recorder.cpp                  # WASAPI audio + DXGI screen capture + FFmpeg pipe
│   ├── recorder.h                    # C ABI exports (ctypes-compatible)
│   └── build.bat                     # MSVC build script
│
├── bin/Release/                     # Built recorder.dll (output of native build)
│
├── src/screen_recorder/
│   ├── __init__.py                  # Package metadata
│   ├── __main__.py                  # Entry point (python -m screen_recorder)
│   ├── app.py                       # Application lifecycle & recording pipeline
│   │
│   ├── capture/                     # Screen capture & region selection
│   │   ├── native_recorder.py        # Python wrapper for C++ recorder.dll
│   │   ├── recording_overlay.py       # Animated dotted border overlay (REC indicator)
│   │   ├── region_selector.py        # Region selection overlay (8 handles)
│   │   └── screen_capture.py         # Fallback capture
│   │
│   ├── config/                      # Configuration & persistence
│   │   ├── hotkey_manager.py         # Global keyboard shortcuts (F9)
│   │   ├── recording_history.py      # Recording history (JSON storage)
│   │   └── settings_manager.py       # QSettings-based configuration
│   │
│   ├── gui/                         # PyQt6 user interface
│   │   ├── main_window.py            # Main application window
│   │   ├── recorder_controls.py      # Start/stop/pause buttons
│   │   ├── settings_panel.py          # Settings configuration panel
│   │   ├── status_bar.py             # Recording status (duration + FPS)
│   │   ├── history_panel.py          # Recording history (delete from disk)
│   │   ├── audio_meter.py            # Real-time audio level meter
│   │   └── system_tray.py            # System tray icon & menu
│   │
│   └── utils/                        # Utilities
│       └── logger.py                  # Logging configuration
│
├── resources/                        # Application resources
│   └── icons/                         # App icon (pyshine_logo.png, app.ico)
│
└── docs/                             # Documentation
    └── ARCHITECTURE.md                # Architecture & design document
```

---

## Architecture

For a detailed overview of the application architecture, threading model, data flow, and module design, see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

Key architectural highlights:

- **Native C++ engine** — `recorder.dll` handles WASAPI audio capture and DXGI Desktop Duplication screen capture on native `std::thread`s (no Python GIL, no tick sounds, perfect A/V sync)
- **A/V sync gate** — audio writing is gated on the first video frame (`g_video_first_frame_written` flag); audio sample 0 corresponds exactly to video frame 0
- **Duplicate-frame catch-up** — when the pipeline falls behind, duplicate frames are written to fill the gap (instead of skipping frames), ensuring the video timeline never falls behind audio
- **Cached staging texture** — the D3D11 staging texture is created once and reused for every frame, eliminating per-frame GPU allocation overhead
- **Box-filter downscaling** — 4K to 1080p uses 2x2 area-averaging (theoretically optimal), non-2x ratios use bilinear interpolation
- **Even-dimension enforcement** — both encode dimensions are forced even for `yuv420p` chroma subsampling compatibility
- **Overlay outside capture** — the recording boundary is drawn in a margin ring OUTSIDE the recorded rectangle, guaranteeing it never appears in the video
- **Two-pass muxing** — video and audio are captured to separate temp files, then muxed by FFmpeg into the final MP4
- **Region crop in C++** — the selected region is cropped at capture time in the native engine

---

## Configuration

Settings are stored in the platform's standard configuration directory:

| Platform | Path |
|---|---|
| Windows | `%APPDATA%\ScreenRecorder\PyQtScreenRecorder\settings.json` |
| Linux | `~/.config/ScreenRecorder/PyQtScreenRecorder/settings.json` |

### Available Settings

| Category | Setting | Default | Description |
|---|---|---|---|
| **Video** | `frame_rate` | `30` | Capture FPS (30 or 24) |
| **Audio** | `microphone_enabled` | `true` | Enable microphone capture |
| | `system_audio_enabled` | `false` | Enable system audio loopback (auto-enabled when mic is off) |
| **General** | `output_directory` | `~/Documents/Screen Recordings` | Output folder |
| | `minimize_to_tray` | `true` | Minimize to system tray |
| | `show_notifications` | `true` | Show desktop notifications |
| | `theme` | `dark` | UI theme |

---

## Audio Notes

### WASAPI Capture (System Audio + Microphone)

Audio capture on Windows uses **WASAPI** via the native C++ engine. When microphone is enabled, the engine captures from the microphone endpoint; when disabled, it automatically falls back to system audio loopback (eRender + loopback).

**Requirements:**
- Windows 10+ (WASAPI is a Windows-specific API)
- The native `recorder.dll` must be present (bundled in the EXE)

### A/V Sync Mechanism

The native engine ensures perfect audio/video synchronization through:

1. **Audio start gate** — audio capture starts immediately but drops all data until `g_video_first_frame_written` is set, ensuring audio sample 0 aligns with video frame 0
2. **Duplicate-frame catch-up** — when the video pipeline falls behind, duplicate frames are written to fill the gap instead of skipping, keeping the video timeline continuous
3. **Strict CFR video PTS** — frame-indexed presentation timestamps (0, 1, 2, ...) guarantee constant frame rate
4. **Cumulative audio PTS** — audio PTS advances by sample count per chunk for sample-accurate linear progression

---

## Changelog

### v1.0.8

- **Fix: audio noise/clicks on peak samples** — the float32 → int16 conversion in the native engine used `lroundf(v * 32768.0f)`, which overflowed `int16_t` when `v == 1.0f` (`32768` wraps to `-32768`, producing a loud negative spike on every peak). The conversion now multiplies by `32767.0f` and clamps at the `long` stage **before** the cast, eliminating the wrap.
- **Fix: A/V drift after silent periods** — WASAPI loopback delivers zero packets when the system is silent, so `g_audio_data_size` stopped advancing and later audio was written at the wrong position. Wall-clock silence padding now fills the gap with zeros (only when `packet_length == 0`, with a 50 ms tolerance to avoid jitter contamination), keeping the audio timeline locked to the video timeline.
- **Fix: `AUDCLNT_BUFFERFLAGS_SILENT` packets** are now explicitly written as zeros instead of being skipped, preventing the audio timeline from shifting forward during system silence.
- **UX: auto-switch capture mode to "Custom Region"** when the region-select button is clicked (no need to change the dropdown manually).
- **UX: friendlier stop dialog** — the modal shown while FFmpeg muxes the final MP4 now reads "This may take a while, please wait…" instead of mentioning muxing internals.
- **Fix: blank thumbnails** — the thumbnail generator now seeks ~1 s into the video and picks the first non-black frame (brightness > 30), falling back to the first frame if all are black.

### v1.0.7

- Professional dark-themed UI with indigo accents, PyShine branding, help dialog, and 100% A/V sync via producer-consumer architecture.

### v1.0.6

- Near-lossless CRF 1 quality, cached GPU staging texture, and A/V sync fixes.

---

## Release Process

For maintainers releasing a new version:

1. **Bump version** in `src/screen_recorder/__init__.py`
2. **Build the DLL**: `native\build.ps1`
3. **Build the EXE**: `python scripts\build_windows.py`
4. **Tag the release**:
   ```bash
   git tag v1.0.8
   git push origin v1.0.8
   ```
5. **Create GitHub Release** with release notes and upload `ScreenRecorder.exe`

---

## Contributing

Contributions are welcome! Here's how to get started:

1. **Fork** the repository on GitHub
2. **Create a feature branch**: `git checkout -b feature/my-new-feature`
3. **Make your changes** and add tests where applicable
4. **Commit** with a descriptive message
5. **Push** to your fork: `git push origin feature/my-new-feature`
6. **Open a Pull Request** against the `main` branch

---

## License

This project is licensed under the **MIT License** — see the [LICENSE](LICENSE) file for details.
