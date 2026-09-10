# Worked examples

All commands assume the package is installed (`pip install -e .`) and that you
are recording the primary monitor.

## 1. Record the markers

Start the recorder, then run the WHS mobile process as you normally would. Each
click or Enter that visibly changes the screen raises a labelling popup; give the
step a title, add notes if useful, and tick "Loading / transition screen" for the
frames you do not want in the document.

```
whs-recorder mark --out runs/receiving/step_markers.json
```

Press `Ctrl+Shift+End` to stop. The markers are saved on the way out, including
when the recorder is stopped some other way.

Fewer steps than you expected? Lower `--threshold` (default `7.5`). Too many,
because of a blinking cursor or a clock? Raise it.

```
whs-recorder mark --out runs/receiving/step_markers.json --threshold 12 --min-gap 1.0
```

Record the screen itself with whatever you already use (Xbox Game Bar, OBS,
Teams). The recorder only produces markers; it does not capture video.

## 2. Build the document

```
whs-recorder build ^
  --video runs/receiving/receiving.mp4 ^
  --markers runs/receiving/step_markers.json ^
  --out runs/receiving/evidence ^
  --title "WHS Receiving - Test Evidence" ^
  --skip-loading
```

The output folder gets a timestamped run folder holding the document, the
screenshots and a `steps.json` manifest.

## 3. Build with redaction

```
whs-recorder build ^
  --video runs/receiving/receiving.mp4 ^
  --markers runs/receiving/step_markers.json ^
  --out runs/receiving/evidence ^
  --redact examples/redaction.sample.json ^
  --skip-loading
```

Redaction is applied before any image is written, so the run folder never
contains an unredacted screenshot. See [PRIVACY.md](../docs/PRIVACY.md) for the
rule format.

Tune the rules against a single screenshot first, which is far quicker than
rebuilding the whole document:

```
whs-recorder redact-preview --image shot.png --redact examples/redaction.sample.json --out preview.png --label
```

## 4. Result messages

By default the builder scans the 2.5 seconds after each marker and picks the
frame that shows the WHS confirmation banner: green for success, red for an
error, amber for a warning. The document captions that screenshot accordingly,
and `steps.json` records which banner was found.

Give a slow device more room:

```
whs-recorder build ... --result-window 4.0
```

If your device theme has no coloured banner, fall back to fixed offsets:

```
whs-recorder build ... --no-toast --result-offsets 0.8,1.5
```

## The markers file

```json
{
  "start_epoch": 1772452800.0,
  "monitor_index": 1,
  "diff_threshold": 7.5,
  "markers": [
    {
      "t": 12.482,
      "reason": "enter",
      "diff": 31.7,
      "title": "Scan licence plate",
      "notes": "LP from the pallet label",
      "is_loading": false
    }
  ]
}
```

It is plain JSON, so a title typo is easier to fix here than to re-record. `t` is
seconds from the start of the recorder, which must be the start of the recording
for the markers to line up.
