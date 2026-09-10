![License](https://img.shields.io/badge/license-GPLv3-blue.svg)
![Status](https://img.shields.io/badge/status-early--beta-orange)
![Platform](https://img.shields.io/badge/platform-Windows-lightgrey)
# Mobile-app-task-recorder
Offline evidence builder for D365 WMS mobile processes. Generates Task Recorder–style documentation from screen recordings using smart interaction markers, OCR, and automated Word output. Designed for consultants and implementation teams.

Finance and operations apps have Task Recorder. The WHS mobile app does not.
This tool fills that gap: it records what you do on the handheld and produces the
same kind of task guide, down to how the step sentences are generated. See
[docs/TASK_RECORDER.md](docs/TASK_RECORDER.md) for the mapping.

## How it works

1. **Mark** — run the recorder alongside your own screen capture. Every tap or
   Enter that visibly changes the screen raises a popup asking what the action
   was: the button or field, the value, and any title or note. It shows the
   sentence your answers will produce.
2. **Build** — point the builder at the recording and the video. It picks a
   legible frame per step, applies your redaction rules, and writes the Word
   document.

Nothing leaves the machine. There is no telemetry and no network call.

## Install

```
pip install -e .
```

Optional extras: `pip install .[ocr]` for text-pattern redaction (also needs a
Tesseract install), `pip install .[dev]` to run the tests.

## Quick start

```
whs-recorder mark --out runs/receiving/recording.json ^
                  --name "Receive a purchase order line"

whs-recorder preview --markers runs/receiving/recording.json

whs-recorder build --video runs/receiving/receiving.mp4 ^
                   --markers runs/receiving/recording.json ^
                   --out runs/receiving/guide ^
                   --redact examples/redaction.sample.json ^
                   --skip-loading
```

While recording: `Ctrl+Shift+S` starts a subtask, `Ctrl+Shift+E` ends it,
`Ctrl+Shift+I` adds an info step, `Ctrl+Shift+End` stops and saves. More recipes
are in [examples/README_examples.md](examples/README_examples.md).

## Step text

Step sentences are generated the way Task Recorder generates them, from the
action and the control rather than from free text:

| You record | The guide reads |
| --- | --- |
| Tap, control `Inbound` | Tap Inbound. |
| Scan, control `LP`, value `LP000123` | In the LP field, scan 'LP000123'. |
| Enter, control `Quantity`, value `12` | In the Quantity field, enter '12'. |
| Check, control `Full pallet`, value `true` | Select Full pallet. |

`--values example` switches every field step to "enter a value" wording, for a
guide that should not carry your test data. A step can also override its own
sentence. The label table lives in `instructions.py`.

## Documents

`--style task-guide` (the default) writes the Task Recorder layout: the recording
name, its description, subtask headings, numbered steps with their titles, notes
and one screenshot each.

`--style evidence` writes the test-evidence layout instead, pairing each step's
action screenshot with the screenshot of its result.

## Redaction

Screenshots are redacted before they are written to disk, so no unredacted image
is ever created. Rules are JSON: fixed regions (no OCR, never miss) and text
patterns (OCR, best effort). Check a rule set against one screenshot with
`whs-recorder redact-preview`. See [docs/PRIVACY.md](docs/PRIVACY.md).

## Result-message detection

WHS mobile confirms an action with a coloured banner that is gone in under a
second, so a fixed "grab the frame 0.6s later" rule misses it on a slow device.
The builder scans the window after each step, prefers the frame that actually
shows a banner, and captions it by kind: success, error or warning. A banner that
is already present at the step is app chrome, not a result, and is ignored.

Result screenshots are on by default in the evidence style. Add `--with-result`
to put them in a task guide too, or `--no-toast` to fall back to fixed offsets.

## Tests

```
pip install .[dev]
pytest
```

The suite runs headless: no camera, no display and no capture stack needed.
