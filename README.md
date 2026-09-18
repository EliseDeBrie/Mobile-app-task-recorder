![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Status](https://img.shields.io/badge/status-early--beta-orange)
![Platform](https://img.shields.io/badge/platform-Windows-lightgrey)
# Mobile-app-task-recorder
Offline evidence builder for D365 WMS mobile processes. Generates Task Recorder–style documentation from screen recordings using smart interaction markers, OCR, and automated Word output. Designed for consultants and implementation teams.

An independent tool from D365Solutions. It is not affiliated with, nor endorsed
by, the vendors of the products it works alongside.

Finance and operations apps have Task Recorder. The WHS mobile app does not.
This tool fills that gap: it records what you do on the handheld and produces the
same kind of task guide, down to how the step sentences are generated. See
[docs/TASK_RECORDER.md](docs/TASK_RECORDER.md) for the mapping.

## How it works

1. **Record** — drag a rectangle over the warehouse app window, the way
   Greenshot and PowerPoint's screen clipping work. Then work through the
   process as you normally would, with nothing to answer: every tap or Enter
   that visibly changes that region is written down by itself, reading the
   screen for the field, the button and the value. Each step captures the app
   region twice — at the action, and again over the next couple of seconds,
   keeping the frame that shows the result banner; your next tap ends that
   watch, so nothing waits on it. A small bar beside the app shows the step
   count and has the stop button on it.
2. **The document is made** the moment you stop — a Word file with the same
   name as the recording, beside it — and the recorded steps open in a list,
   each with its screenshot. Correct any wording the screen was read wrong,
   leave out anything that does not belong in the guide, and reorder what is
   out of place. Saving remakes the document; pressing Done opens it.

What ends up in the folder: `Receive a purchase order line.docx` is the
document. `Receive a purchase order line.json` is the recording it was made
from, which 'Check the steps' reopens, and the `_screenshots` and `_build`
folders beside them hold the pictures. The command line does the same with
`build --document`.

Because the app is a window on the PC rather than a page in a browser, there is
no tab for an extension to photograph, which is how Task Recorder gets its
screenshots. Watching one region solves the other half of the problem too: the
clock and the taskbar can no longer trigger steps of their own.

The Warehouse Management mobile app is installed from an app store or
sideloaded, on Windows, Android and iOS. A browser extension cannot see any of
them, since extensions only ever see browser tabs. The one exception is the
browser-based emulator inside Supply Chain Management, which the product
documentation warns is not a substitute for the real app.

Nothing leaves the machine. There is no telemetry and no network call.

## Install

Go to the [latest release](https://github.com/EliseDeBrie/Mobile-app-task-recorder/releases/latest)
and download **WHS.Task.Recorder.exe** from the **Assets** list at the bottom of
that page. It is about 80 MB.

The executable is not in the repository itself, and it is not in the green
**Code** button's zip: that is the source. It is only ever on the Releases page,
where each version is built and attached by CI. (GitHub shows the file with dots
instead of spaces; rename it back to `WHS Task Recorder.exe` if you like, or
leave it - it makes no difference.)

Then just run it. There is nothing else to install: no Python, no packages, no
terminal. Double-clicking opens a window with everything in it, and no console
window appears at any point.

The same file is also the command line. Run it from a terminal with arguments
and it prints into that terminal, which is how the options the window does not
offer are reached.

The launcher's title bar carries the version, so you can always tell which
build you are running.

Windows warns that a downloaded program is unsigned the first time you run it.
Choose **More info**, then **Run anyway**. Signing the program would remove that
warning and costs a certificate; until then the warning is expected.

### Installing from source instead

For working on the tool, or running it from a checkout:

```
pip install -e .
```

Optional extras: `.[ocr-windows]` for the OCR engine built into Windows,
`.[ocr]` for Tesseract, `.[window]` to find the app by window title, `.[dev]` to
run the tests.

## Installing without administrator rights

The executable needs nothing at all: no install, no administrator. Running from
source needs no administrator either, which matters on a customer's machine:

| Piece | How to get it as a plain user |
| --- | --- |
| Python | Clear "Install for all users" in the installer, or use the Store build |
| The packages | `pip install --user` |
| OCR | `.[ocr-windows]` uses the engine already in Windows; only wheels are installed |
| Tesseract, if you prefer it | Unpack a portable copy and pass `--tesseract`, or put it in `%LOCALAPPDATA%\whs-recorder\tesseract` |
| Screen capture and the key watcher | Nothing to install and no elevation |

Run `whs-recorder check` on a new machine. It reports what is present, what is
missing, and the command to fix each gap without an administrator:

```
ok   Python: 3.12.4, installed for this user
ok   mss: capturing the screen
ok   OCR: windows: built into Windows, nothing to install - in use
ok   OCR: reading a test image with windows: read "WHS RECORDER 12345"
Everything needed to record and build is present.
None of it needs administrator rights.
```

The last line of that report is the useful one: it prints a test image, reads it
back through whichever engine is live, and shows you what came out. An engine
that loads but reads badly is caught there rather than mid-recording.

One thing to watch: if the warehouse app itself runs as administrator, a
recorder running as a normal user will not see its taps and keys. Run both the
same way.

## Quick start

```
whs-recorder mark --out runs/receiving/recording.json ^
                  --name "Receive a purchase order line"

whs-recorder review --markers runs/receiving/recording.json

whs-recorder preview --markers runs/receiving/recording.json

whs-recorder build --markers runs/receiving/recording.json ^
                   --out runs/receiving/guide ^
                   --document runs/receiving/Receiving.docx ^
                   --redact examples/redaction.sample.json ^
                   --skip-loading
```

Each build goes into a run folder of its own under `--out`, with its pictures
and a manifest, so no build overwrites another; `--document` also places the
finished document at one fixed name, replacing the previous one.

`mark` opens the region selector first. To skip the drag, name the window with
`--region "window:Warehouse"` (needs `pip install .[window]`), give coordinates
with `--region 220,140,360,640`, or watch the whole screen with `--region full`.

While recording: `Ctrl+Shift+S` starts a subtask, `Ctrl+Shift+E` ends it,
`Ctrl+Shift+I` adds an info step, `Ctrl+Shift+End` stops and saves — or press
**Stop recording** on the bar beside the app. More recipes are in
[examples/README_examples.md](examples/README_examples.md).

`review` reopens that list for any recording, so a guide can be reworded long
after it was recorded. Nothing is written to the file until you press Save.

If you would rather name each step as you take it, `mark --ask-each-step`
restores the popup that asks about every action.

## What each step records

A step holds the same things a Task Recorder step holds, as text:

| Field | Example | Where it comes from |
| --- | --- | --- |
| Screen | `Purchase receive` | Read from the title bar, and carried over until it changes |
| Action | `scan` | Inferred from whether you typed a value, and corrected in the review window |
| Control | `Purchase order` | Read from the label above the tap |
| Value | `PO000045` | Read from the text that appeared where you tapped |
| Title, note | your words | Typed in the review window |

All of it is read off the screen while you work, and all of it is editable
afterwards. The reading is deliberately cautious: a tap it cannot make out
leaves the box empty rather than guessing, which is easy to spot and fill in
from the screenshot beside it. Turn the reading off entirely with
`--no-suggest`.

Two engines can do the reading. Windows OCR is part of Windows 10 and 11 and is
used by default: nothing is installed for it beyond a `pip install`, and it
needs no administrator. Tesseract is used when Windows OCR is unavailable; its
usual installer wants an administrator, so point `--tesseract` at a portable
copy instead. `whs-recorder check` says which engine is live.

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

If you would rather record video anyway — evidence that has to show real time,
say — pass `--no-screenshots` while
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
