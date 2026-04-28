# Gameplay Recorder

A standalone PySide6 desktop application for recording Android gameplay sessions (video + raw touch events) and packaging them as ZIPs for offline ML training dataset ingestion.

## Features

- ADB-based device discovery and connection
- Segmented video capture via `adb screenrecord` (no 180s limit workaround)
- Raw touch event capture via `adb shell getevent`
- Periodic screenshots at configurable interval (default: 5s)
- ZIP packaging with session metadata
- IP-clean output (no ML-internal fields in public ZIPs)
- Auto-update check via GitHub Releases

## Install

> **Note**: These are placeholder instructions. Full install guide coming in a future release.

```bash
pip install gameplay-recorder
```

Or clone and install in editable mode:

```bash
git clone https://github.com/MarioPradEs/gameplay_recorder.git
cd gameplay_recorder
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate
pip install -e ".[dev]"
```

## Usage

```bash
gameplay-recorder
# or
python -m gameplay_recorder
```

## License

MIT — see [LICENSE](LICENSE).

Repository: <https://github.com/MarioPradEs/gameplay_recorder>

---

## TODO

### macOS Gatekeeper Workaround

> This section will document how to bypass Gatekeeper for unsigned `.app` bundles on macOS.
> Placeholder for a future batch.
