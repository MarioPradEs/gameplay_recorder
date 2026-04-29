# Test Suite — gameplay_recorder

## Structure

```
tests/
  unit/
    adb/           # AdbConnection, device discovery
    capture/       # TouchEventMonitor, VideoSegmentRecorder, ScreenshotCapture
    models/        # RawTouchEvent, SessionMeta, RecordingState
  integration/     # Real-device tests (gated by GAMEPLAY_RECORDER_E2E=1)
```

## Running Tests

```bash
# Unit tests (fast, no device needed)
.venv/Scripts/python.exe -m pytest tests/unit/

# With coverage
.venv/Scripts/python.exe -m pytest tests/unit/ --cov=gameplay_recorder

# Integration tests (requires connected device)
GAMEPLAY_RECORDER_E2E=1 .venv/Scripts/python.exe -m pytest tests/
```

## TDD Mode

**Strict TDD is active** — every production module has a RED test written before
its production code. See `.sdd/` or engram for the full TDD cycle evidence.

---

## Mock Hygiene Convention (MANDATORY)

### Rule: All mocks of external-class objects MUST use `spec=<RealClass>`

```python
# ✅ CORRECT — spec= catches API drift at test time
from gameplay_recorder.adb.connection import AdbConnection
mock_conn = MagicMock(spec=AdbConnection)

# ❌ WRONG — plain MagicMock accepts ANY method call, even non-existent ones
mock_conn = MagicMock()  # .shell(), .shell_stream() — any call silently accepted
```

### Why this matters — the bugs it caught

**Three critical API bugs** escaped unit tests because mocks lacked `spec=`:

| Bug | Symptom | How mock hid it |
|-----|---------|-----------------|
| C1: `AdbConnection.shell()` missing | `AttributeError` at runtime | `MagicMock()` accepted `.shell()` even though the method didn't exist |
| C2: `AdbDevice.shell(encoding=None)` wrong signature | `TypeError` at runtime | `MagicMock()` accepted `encoding=None` kwarg that doesn't exist in adbutils |
| C3: `AdbDevice.shell_stream()` missing | `AttributeError` at runtime | `MagicMock()` accepted `.shell_stream()` even though it doesn't exist |
| Prev: `AdbClient.list()` missing | `AttributeError` at runtime | Same root cause — caught via `spec=AdbClient` regression tests |

### Which classes MUST be spec'd

| Class being mocked | Correct pattern |
|--------------------|----------------|
| `AdbConnection` (ours) | `MagicMock(spec=AdbConnection)` |
| `adbutils.AdbClient` | `MagicMock(spec=adbutils.AdbClient)` |
| `subprocess.CompletedProcess` | OK as plain mock (returned from `subprocess.run()`) |
| `subprocess.Popen` | `MagicMock(spec=subprocess.Popen)` for new tests |
| `PySide6.QtCore.QThread` | OK as plain mock (too complex to spec) |

### Exception: pytest-asyncio hang with `spec=adbutils.AdbDevice`

**Known issue**: `MagicMock(spec=adbutils.AdbDevice)` causes a hang when run
via pytest with `asyncio_mode = "auto"`. This is because pytest-asyncio
inspects all class attributes to find coroutines, and `adbutils.AdbDevice`
imports `requests` and other packages that trigger network activity during
attribute inspection.

**Workaround**: For mocks of `adbutils.AdbDevice`, use plain `MagicMock()` and
verify the API contract via explicit assertions (e.g., check `stream=True` was
passed, check `shell_stream` was never called). The `spec=AdbConnection` pattern
on our own class is sufficient to catch drift at the boundary we control.

### Enforcing the rule in new tests

When writing a test that mocks `AdbConnection` or any adbutils class:

1. Import the real class at the top of the test module
2. Use `MagicMock(spec=RealClass)` for the mock
3. The mock will raise `AttributeError` immediately if production code calls
   a method that doesn't exist — catching bugs before they reach production

```python
# Standard pattern for all new capture tests:
from gameplay_recorder.adb.connection import AdbConnection

def test_something():
    mock_conn = MagicMock(spec=AdbConnection)
    mock_conn.shell.return_value = "expected output"
    # If production code calls a non-existent method → AttributeError immediately
```
