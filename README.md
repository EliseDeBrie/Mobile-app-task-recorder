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

1. **Mark** — drag a rectangle over the warehouse app window, the way Greenshot
   and PowerPoint's screen clipping work. Every tap or Enter that visibly
   changes that region raises a popup asking what the action was: the button or
   field, the value, and any title or note. It shows the sentence your answers
   will produce, and it captures the app region twice per step: at the action,
   and again over the next couple of seconds, keeping the frame that shows the
   result banner.
2. **Build** — point the builder at the recording. It redacts the screenshots
   and writes the Word document.

Because the app is a window on the PC rather than a page in a browser, there is
no tab for an extension to photograph, which is how Task Recorder gets its
screenshots. Watching one region solves the other half of the problem too: the
clock and the taskbar can no longer trigger steps of their own.

The Warehouse Management mobile app is installed from the Microsoft Store or
sideloaded, on Windows, Android and iOS. A browser extension cannot see any of
them, since extensions only ever see browser tabs. The one exception is the
browser-based emulator inside Supply Chain Management, which Microsoft's own
documentation warns is not a substitute for the real app.

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

whs-recorder build --markers runs/receiving/recording.json ^
                   --out runs/receiving/guide ^
                   --redact examples/redaction.sample.json ^
                   --skip-loading
```

`mark` opens the region selector first. To skip the drag, name the window with
`--region "window:Warehouse"` (needs `pip install .[window]`), give coordinates
with `--region 220,140,360,640`, or watch the whole screen with `--region full`.

While recording: `Ctrl+Shift+S` starts a subtask, `Ctrl+Shift+E` ends it,
`Ctrl+Shift+I` adds an info step, `Ctrl+Shift+End` stops and saves. More recipes
are in [examples/README_examples.md](examples/README_examples.md).

## What each step records

A step holds the same things a Task Recorder step holds, as text:

| Field | Example | Where it comes from |
| --- | --- | --- |
| Screen | `Purchase receive` | Read from the title bar, and carried over until it changes |
| Action | `scan` | Chosen in the popup |
| Control | `Purchase order` | Read from the label above the tap |
| Value | `PO000045` | Read from the text that appeared where you tapped |
| Title, note | your words | Typed in the popup |

Where OCR is available the popup opens with the screen, control and value
already filled in, and you correct what is wrong. Without it the popup is blank
and you type all three. Suggestions are deliberately cautious: a tap it cannot
read leaves the box empty rather than guessing. Turn the reading off with
`--no-suggest`.

Expect to type button names yourself. Field labels are dark text on a light
background and read reliably; a button's white label on a coloured fill often
does not, so those steps come back blank.

The screen name is what gives the guide its bearings: it is printed once
whenever it changes, as `On the Purchase receive screen:`.

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

## Screenshots

The recorder captures the app region itself, so a separate screen recording is
optional. Captures are PNG, straight from the screen, with none of the softening
a video codec introduces.

If you would rather record video anyway — a process too fast to interrupt with
popups, or evidence that has to show real time — pass `--no-screenshots` while
recording and `--video` when building. The builder then selects a frame per step
from the video, and crops it to the region if the video covers the whole screen.

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
