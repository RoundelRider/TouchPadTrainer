# TouchPad Test Program

A cross-platform desktop application (Windows / macOS) for administering
capacitive touch-pad reaction-time tests using an Arduino controller.
Built with **Python 3.11+**, **PyQt6**, and **PySerial**.

---

## Table of Contents

- [Overview](#overview)
- [Requirements](#requirements)
- [Installation](#installation)
- [Running the Application](#running-the-application)
- [Project Layout](#project-layout)
- [Hardware Setup](#hardware-setup)
- [Quick-Start Workflow](#quick-start-workflow)
- [Features](#features)
- [Configuration File Format](#configuration-file-format)
- [Arduino Serial Protocol](#arduino-serial-protocol)
- [Running the Tests](#running-the-tests)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)

---

## Overview

The TouchPad Test Program drives a 4×4 capacitive touch-pad panel (or up to
four panels simultaneously) through a configurable reaction-time test.  It
records whether each pad was touched, how quickly, and produces per-trial CSV
exports and in-app statistical summaries suitable for clinical, sports-science,
or research use.

---

## Requirements

| Requirement | Minimum version |
|-------------|----------------|
| Python      | 3.11            |
| PyQt6       | 6.6             |
| pyserial    | 3.5             |
| OS          | Windows 10+ or macOS 13+ |

---

## Installation

```bash
# 1 — Clone or download the repository
git clone https://github.com/your-org/touchpad-test-program.git
cd touchpad-test-program

# 2 — Create and activate a virtual environment (recommended)
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

# 3 — Install dependencies
pip install -r requirements.txt
```

---

## Running the Application

```bash
python main.py
```

To increase log verbosity for debugging:

```bash
LOG_LEVEL=DEBUG python main.py
```

Log files are written to:

| Platform | Location |
|----------|----------|
| Windows  | `%APPDATA%\TouchPadProgram\logs\touchpad.log` |
| macOS    | `~/.local/share/TouchPadProgram/logs/touchpad.log` |

---

## Project Layout

```
touchpad/
├── main.py                     # Entry point — app bootstrap & logging setup
├── requirements.txt
├── README.md
│
├── core/                       # Business logic — no Qt imports
│   ├── serial_manager.py       # Serial port connection, command queue, ACK/NAK
│   ├── test_runner.py          # Trial sequencer and randomization engine
│   └── audio.py                # Cross-platform beeps and tones
│
├── data/                       # Data layer — models and persistence
│   ├── models.py               # TestConfiguration, TrialResult, SessionResult
│   └── storage.py              # JSON config store, session history, CSV export
│
├── ui/                         # PyQt6 widgets
│   ├── main_window.py          # QMainWindow — tabs, menu, status bar
│   ├── connection_bar.py       # Port selector toolbar + live status indicator
│   ├── pad_grid.py             # 4×4 PadCell grid (used in test view and results)
│   ├── config_editor.py        # Configuration CRUD editor
│   ├── test_panel.py           # Run Test tab — participant ID, start/cancel
│   ├── results_view.py         # Statistics, per-pad heatmap, session compare
│   ├── session_history.py      # Browsable past-session table
│   ├── calibration.py          # Pad sensitivity calibration + latency test
│   └── settings_dialog.py      # Serial timeout, font size, update prefs
│
├── assets/
│   ├── icons/
│   │   └── app_icon.png
│   └── sounds/
│       └── beep.wav            # Countdown fallback (non-Windows)
│
└── tests/
    ├── test_models.py          # TestConfiguration and TrialResult unit tests
    ├── test_runner.py          # Sequencer tests with mock serial
    └── test_storage.py         # Save / load round-trip tests
```

---

## Hardware Setup

Each **touch panel** contains a 4×4 grid of 16 pads.  Each pad has an LED
array and a capacitive touch surface wired to an **Arduino controller**.

```
PC  ──USB/Serial──►  Arduino  ──►  Panel 1 (pads 1–16)
                              ──►  Panel 2 (pads 1–16)   [optional]
                              ──►  Panel 3 (pads 1–16)   [optional]
                              ──►  Panel 4 (pads 1–16)   [optional]
```

1. Connect the Arduino to the PC via USB.
2. Note the COM port assigned by the OS (e.g. `COM3` on Windows,
   `/dev/tty.usbmodem14101` on macOS).
3. In the application toolbar select that port and click **Connect**.

---

## Quick-Start Workflow

1. **Connect** — select the serial port in the toolbar and click *Connect*.
   The status indicator turns green and the firmware version is displayed.
2. **Orientation check** — go to *Calibration → Orientation Check* and click
   *Light Pad #1* to confirm panel placement and numbering.
3. **Create a configuration** — open the *Configuration* tab, click *New*,
   set the test type, number of trials, timeout, and which pads to include,
   then click *Save Configuration*.
4. **Run a test** — open the *Run Test* tab, enter the participant ID, select
   the configuration, and click *▶ Start Test*.
5. **Review results** — results appear automatically in the *Results* tab when
   the test finishes.  Click *Export CSV* to save a per-trial data file.

---

## Features

### Connection & Communication
- Auto-scan of available COM ports / `/dev/tty*` devices with *Refresh* button.
- Persistent connection status indicator (Connected / Disconnected / Error).
- ACK / NAK acknowledgement for every command sent to the Arduino.
- Configurable serial response timeout (default 5 000 ms).
- Command queue prevents lost commands if commands arrive faster than the
  Arduino can process them.
- Firmware version check on connect — warns the operator if the firmware is
  incompatible with the application version.

### Test Configuration
- Named configurations saved as JSON files; importable and exportable.
- Supports 1–4 panels, individually selectable pads per panel.
- Mark a pad as **faulty** to skip it in all tests without removing it from
  the layout.
- Four test types:
  - *Single Touch — White* (always expect touch)
  - *Single Touch — Selective* (random green/red, configurable ratio)
  - *Double Touch — White* (two adjacent pads, always expect touch)
  - *Double Touch — Selective* (two adjacent pads, random green/red)
- Configurable timeout, number of trials, inter-stimulus interval (ISI),
  warm-up (non-scored) trials, and optional rest breaks.
- Pad order: Random, Pseudo-random (no immediate repeats), or Sequential.
- Up to 5 configurable reaction-time colour bands for result visualisation.
- Configuration versioning with last-modified timestamp.
- Read-only lock to protect reference configurations.

### Test Execution
- Participant / session ID field (results are tagged to a person).
- Countdown beep before test start (Windows native; WAV fallback elsewhere).
- Optional auditory tone at the moment each pad lights up.
- Live 4×4 pad grid mirrors the physical panel in real time.
- Trial progress indicator (Trial N of Total N).
- Cancel button halts the test at any point.

### Results & Data
- Per-session statistical summary: N, mean, median, standard deviation,
  min and max reaction times — overall and per pad.
- Commission error count (touched a *do-not-touch* pad).
- Omission error count (failed to touch an *expected* pad).
- Per-pad result heatmap using the configured colour bands.
- Full per-trial CSV export (participant ID, timestamp, panel, pad,
  expected touch, actual touch, reaction time).
- Session history browser with load and export.
- Side-by-side session comparison (mean RT delta).

### Calibration & Diagnostics
- Pad sensitivity calibration routine per panel/pad.
- Round-trip serial latency measurement.
- Orientation check (light pad #1 on any panel).

### Accessibility
- Three font-size presets (Small / Medium / Large).
- High-contrast mode (black background, yellow text).

---

## Configuration File Format

Configurations are stored as UTF-8 JSON files in:

| Platform | Location |
|----------|----------|
| Windows  | `%APPDATA%\TouchPadProgram\configs\` |
| macOS    | `~/.local/share/TouchPadProgram/configs\` |

Example:

```json
{
  "name": "Simple Reaction Time",
  "id": "a1b2c3d4-...",
  "read_only": false,
  "last_modified": "2025-04-16T10:30:00",
  "num_panels": 1,
  "pads": [
    { "panel": 0, "pad": 0, "faulty": false },
    { "panel": 0, "pad": 5, "faulty": false }
  ],
  "test_type": 0,
  "timeout_ms": 2000,
  "num_trials": 20,
  "isi_ms": 1000,
  "warmup_trials": 3,
  "rest_every_n": 0,
  "rest_duration_ms": 5000,
  "pad_order": 1,
  "green_red_ratio": 0.5,
  "rt_bands": [
    { "max_ms": 400,  "color": "#00C800", "label": "Excellent" },
    { "max_ms": 800,  "color": "#90EE90", "label": "Good"      },
    { "max_ms": 1200, "color": "#FFD700", "label": "Fair"      },
    { "max_ms": 1600, "color": "#FFD070", "label": "Slow"      },
    { "max_ms": 2000, "color": "#FF3030", "label": "Miss"      }
  ]
}
```

`test_type` values: `0` = Single/White, `1` = Single/Selective,
`2` = Double/White, `3` = Double/Selective.

`pad_order` values: `0` = Random, `1` = Pseudo-random, `2` = Sequential.

---

## Arduino Serial Protocol

All multi-byte values are big-endian.

### Commands (PC → Arduino)

| Code | Name | Payload bytes |
|------|------|---------------|
| `0x01` | Orient On  | `panel`, `color` |
| `0x02` | Orient Off | — |
| `0x03` | Test Start | — |
| `0x04` | Test End   | — |
| `0x05` | Single Touch | `panel`, `pad`, `color`, `flags`, `timeout_hi`, `timeout_lo` |
| `0x06` | Dual Touch   | `panel`, `pad1`, `pad2`, `color`, `flags`, `timeout_hi`, `timeout_lo` |
| `0x07` | Version Query | — |
| `0x08` | Calibrate | `panel`, `pad` |
| `0x09` | Latency Ping | — |

`color`: `0` = White, `1` = Green, `2` = Red.  
`flags`: bit 0 = expect touch (`1`) / do not expect touch (`0`).

### Response (Arduino → PC)

Fixed 6-byte frame:

```
[ status, panel, pad, touched, rt_hi, rt_lo ]
```

| Byte | Meaning |
|------|---------|
| `status` | `0xAA` = ACK (success), `0xFF` = NAK (error) |
| `panel`  | Panel number (0-based) |
| `pad`    | Pad number (0-based) |
| `touched`| `1` if touch recorded, `0` otherwise |
| `rt_hi`  | High byte of reaction time in ms |
| `rt_lo`  | Low byte of reaction time in ms |

Version query returns an ASCII string terminated by `\n`, e.g. `1.0.0\n`.

---

## Running the Tests

```bash
pip install pytest pytest-qt
pytest tests/ -v
```

The test suite does **not** require connected hardware — the serial port is
mocked using `unittest.mock`.

---

## Troubleshooting

**"Not connected" after selecting a port**  
Verify the Arduino is powered and the correct COM port is selected.  On macOS,
use `/dev/tty.usbmodem…` rather than `/dev/cu.usbmodem…`.  Try a different
USB cable.

**Firmware version warning on connect**  
The major version of the Arduino firmware must match the application.  Flash
the latest firmware from the `firmware/` directory (not included in this repo)
before proceeding.

**No COM ports listed**  
On macOS/Linux the user account may need to be added to the `dialout` (Linux)
or `uucp` (macOS) group:  
`sudo usermod -aG dialout $USER` then log out and back in.

**Application fails to start on macOS with "can't open file"**  
Run from the project root directory, not from inside `ui/` or another
subdirectory.

**High CPU usage during a test**  
The serial worker thread polls at 5 ms intervals by default.  This is
intentional for low-latency response collection.  It has no measurable effect
on modern hardware.

---

## Contributing

1. Fork the repository and create a feature branch.
2. Keep `core/` free of Qt imports so unit tests remain fast.
3. Add or update tests in `tests/` for any logic changes.
4. Run `pytest tests/ -v` and confirm all tests pass before opening a pull
   request.
