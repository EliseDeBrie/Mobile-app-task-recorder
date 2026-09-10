![License](https://img.shields.io/badge/license-GPLv3-blue.svg)
![Status](https://img.shields.io/badge/status-early--beta-orange)
![Platform](https://img.shields.io/badge/platform-Windows-lightgrey)
# Mobile-app-task-recorder
Offline evidence builder for D365 WMS mobile processes. Generates Task Recorder–style documentation from screen recordings using smart interaction markers, OCR, and automated Word output. Designed for consultants and implementation teams.

## How it works

1. **Mark** — run the recorder alongside your own screen capture. Every click or
   Enter that visibly changes the screen raises a popup where you name the step.
   The result is a small `step_markers.json`, not a pile of screenshots.
2. **Build** — point the builder at the recording and the markers. For each step
   it picks a legible *action* frame, finds the frame showing the WHS result
   banner, applies your redaction rules, and writes a Word document.

Nothing leaves the machine. There is no telemetry and no network call.

## Install

```
pip install -e .
```

Optional extras: `pip install .[ocr]` for text-pattern redaction (also needs a
Tesseract install), `pip install .[dev]` to run the tests.

## Quick start

```
whs-recorder mark --out runs/receiving/step_markers.json

whs-recorder build --video runs/receiving/receiving.mp4 ^
                   --markers runs/receiving/step_markers.json ^
                   --out runs/receiving/evidence ^
                   --redact examples/redaction.sample.json ^
                   --skip-loading
```

Press `Ctrl+Shift+End` to stop the recorder. More recipes are in
[examples/README_examples.md](examples/README_examples.md).

## Redaction

Screenshots are redacted before they are written to disk, so no unredacted image
is ever created. Rules are JSON: fixed regions (no OCR, never miss) and text
patterns (OCR, best effort). Check a rule set against one screenshot with
`whs-recorder redact-preview`. See [docs/PRIVACY.md](docs/PRIVACY.md).

## Result-message detection

WHS mobile confirms an action with a coloured banner that is gone in under a
second, so a fixed "grab the frame 0.6s later" rule misses it on a slow device.
The builder scans the window after each marker, prefers the frame that actually
shows a banner, and captions it by kind: success, error or warning. A banner that
is already present at the marker is app chrome, not a result, and is ignored.

Turn it off with `--no-toast` to fall back to fixed `--result-offsets`.

## Tests

```
pip install .[dev]
pytest
```

The suite runs headless: no camera, no display and no capture stack needed.
