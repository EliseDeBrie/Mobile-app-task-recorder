# Worked examples

All commands assume the package is installed (`pip install -e .`) and that you
are recording the primary monitor.

## 1. Point the recorder at the app

```
whs-recorder mark --out runs/receiving/recording.json ^
                  --name "Receive a purchase order line" ^
                  --description "How a warehouse worker receives one line of a purchase order."
```

The screen dims and you drag a rectangle over the warehouse app window. Only that
rectangle is watched and only that rectangle is captured, so the desktop behind it
never reaches the guide.

Other ways to say where the app is:

| Option | Use it when |
| --- | --- |
| `--region select` | The default: drag it out. |
| `--region "window:Warehouse"` | The window has a stable title. Needs `pip install .[window]`. |
| `--region 220,140,360,640` | A fixed kiosk layout you script. `whs-recorder region` prints these numbers for you. |
| `--region full` | You want the whole monitor after all. |

Every tap or Enter that visibly changes that region raises a popup. Answer it the
way Task Recorder would have answered itself:

| Field | What to put |
| --- | --- |
| Action | Tap, scan, enter a value, select a row, check box, close, back |
| Button, field or page name | The label on screen: `Inbound`, `LP`, `Quantity` |
| Value | What you scanned or typed, for a scan or an entry |
| Title | Something the reader should know *before* doing the step |
| Note | Something useful *after* it |
| Loading / transition screen | Tick for frames you do not want in the guide |

The popup shows the sentence your answers produce, so you can see the guide being
written as you record. It opens beside the app, never over it, so it stays out of
the screenshots.

Each step is captured twice: once at the action, and again over the next couple of
seconds, keeping the frame that shows the result banner. Screenshots land in a
folder beside the recording, and `--redact` applies your rules as they are
written. Give a slow device more room with `--result-window 4.0`, or turn the
capture off with `--no-screenshots` if you would rather build from a video.

Gestures, mirroring the Task Recorder pane:

| Keys | Effect |
| --- | --- |
| `Ctrl+Shift+S` | Start a subtask and name it |
| `Ctrl+Shift+E` | End the current subtask |
| `Ctrl+Shift+I` | Add an info step for something done away from the device |
| `Ctrl+Shift+End` | Stop and save |

The recording is saved on the way out, including when the recorder is stopped
some other way.

Fewer steps than you expected? Lower `--threshold` (default `7.5`). Too many,
because of a blinking cursor or a clock? Raise it.

## 2. Read the guide before you build it

```
whs-recorder preview --markers runs/receiving/recording.json --skip-loading
```

```
Receive a purchase order line
How a warehouse worker receives one line of a purchase order on the handheld.

[Open purchase receive]
      1. Tap Inbound.
      2. Tap Purchase receive.

[Receive the line]
        Scan the bar code on the paperwork, do not type it.
      3. In the Purchase order field, scan 'PO000045'.
      4. In the Quantity field, enter '12'.
      5. Put the pallet in the staging lane before you confirm.
      6. Select Full pallet.
      7. Tap Confirm.
```

Fix any wording in the recording JSON, which is plain text and far quicker to
edit than to re-record.

## 3. Build the task guide

```
whs-recorder build --markers runs/receiving/recording.json ^
                   --out runs/receiving/guide ^
                   --redact examples/redaction.sample.json ^
                   --skip-loading
```

The output folder gets a timestamped run folder holding the document, the
screenshots and a `steps.json` manifest.

For a training guide that should not carry your test data, switch the field steps
to example wording:

```
whs-recorder build ... --values example
```

## 4. Build test evidence instead

```
whs-recorder build ... --style evidence --title "WHS Receiving - UAT evidence"
```

The evidence style pairs each step's action screenshot with the screenshot of its
result, and keeps the provenance lines naming the video and the recording. To get
the result screenshots inside a task guide, use `--with-result`.

## 5. Building from a screen recording instead

Some processes are too fast to interrupt with a popup per step, and some evidence
has to show real elapsed time. Record with `--no-screenshots`, capture the screen
with whatever you use (Xbox Game Bar, OBS, Teams), and build with a video:

```
whs-recorder mark --out runs/receiving/recording.json --no-screenshots
whs-recorder build --video runs/receiving/receiving.mp4 ^
                   --markers runs/receiving/recording.json ^
                   --out runs/receiving/guide
```

The builder picks a legible frame per step and crops it to the app region, so a
full-screen recording still yields screenshots of the app alone. The recorder
must start with the screen capture for the timestamps to line up.

For the result screenshot it scans the 2.5 seconds after each step and picks the
frame showing the WHS confirmation banner: green for success, red for an error,
amber for a warning. Give a slow device more room with `--result-window 4.0`. If
your device theme has no coloured banner, use `--no-toast --result-offsets 0.8,1.5`.

## 6. Redaction

```
whs-recorder redact-preview --image shot.png --redact examples/redaction.sample.json --out preview.png --label
```

Tune the rules against one screenshot before rebuilding a whole document. See
[PRIVACY.md](../docs/PRIVACY.md) for the rule format.

## The recording file

```json
{
  "format": "whs-task-recording",
  "version": 3,
  "name": "Receive a purchase order line",
  "description": "How a warehouse worker receives one line of a purchase order.",
  "start_epoch": 1772452800.0,
  "region": {"left": 220, "top": 140, "width": 360, "height": 640, "source": "select"},
  "nodes": [
    {"type": "subtask_start", "t": 0.3, "name": "Receive the line"},
    {
      "type": "step",
      "t": 12.482,
      "action": "scan",
      "control": "Purchase order",
      "value": "PO000045",
      "title": "Scan the bar code on the paperwork, do not type it.",
      "note": "",
      "user_text": "",
      "instruction_label": null,
      "hidden": false,
      "is_loading": false,
      "action_img": "recording_screenshots/step_01_action.png",
      "result_img": "recording_screenshots/step_01_result.png",
      "result_toast": "success"
    },
    {"type": "info", "t": 20.1, "text": "Put the pallet in the staging lane"},
    {"type": "subtask_end", "t": 24.0}
  ]
}
```

`t` is seconds from the start of the recorder, which must be the start of the
screen capture for the frames to line up. `user_text` overrides the generated
sentence, and `instruction_label` overrides the template it is built from, either
by label ID or with your own text such as `"Press %1 twice."`. Files written
before v0.3, with a flat `markers` list, still load.
