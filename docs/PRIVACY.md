# Privacy and redaction

Evidence recordings of WHS mobile processes routinely capture things a test
document should not carry: the signed-in worker, badge numbers, licence plates,
customer names on a pick list. This page describes what the tool stores and how
to keep that material out of the generated document.

## What the tool stores

Everything stays on the machine that runs it. There is no telemetry, no upload
and no network call in any code path.

| Artefact | Written by | Contains |
| --- | --- | --- |
| the recording JSON | `whs-recorder mark` | Timestamps, the action, control and value of each step, your titles and notes, and the screen-change score. No pixels. |
| `run_<stamp>/step_*.jpg` | `whs-recorder build` | The screenshots, after redaction. |
| `run_<stamp>/steps.json` | `whs-recorder build` | The per-step manifest: generated instructions, titles, notes, image paths, which rules were applied. |
| `run_<stamp>/<recording name>.docx` | `whs-recorder build` | The document, with the redacted screenshots embedded. |

The values you scan and type are part of the recording, and the generated steps
repeat them ("In the LP field, scan 'LP000123'"). Build with `--values example`
to replace them with "enter a value" wording, which keeps live data out of a
guide that will be shared widely.

The source recording is only ever read. Redaction happens before an image is
written to disk, so no unredacted screenshot is ever created, and the document
cannot embed one.

The recording itself is **not** redacted. It is your original evidence, and it
still holds everything that was on screen. Treat the MP4 as confidential, and
share the generated folder rather than the recording.

## Writing redaction rules

Rules live in a JSON file that you pass to `--redact`. A copy you can start from
is in [`examples/redaction.sample.json`](../examples/redaction.sample.json).

```json
{
  "default_mode": "box",
  "label": false,
  "regions": [
    {"name": "signed-in user", "box": [0.0, 0.0, 1.0, 0.06]},
    {"name": "worker badge", "box": [820, 40, 1080, 96], "units": "absolute", "mode": "blur"}
  ],
  "text_patterns": [
    {"name": "licence plate", "pattern": "LP[0-9]{6,}", "mode": "pixelate"}
  ]
}
```

### Region rules

A region rule masks the same rectangle on every screenshot. Use it for anything
that sits in a fixed place: the header carrying the user name, a status line, a
device identifier in a corner.

* `box` is `[x1, y1, x2, y2]`.
* `units` is `relative` (the default, fractions of width and height, so the rule
  survives a change of device resolution) or `absolute` (pixels).
* `mode` is `box` (solid black), `blur` or `pixelate`.

Region rules need no OCR and never miss. Prefer them.

### Text rules

A text rule masks any word matching a regular expression, wherever it appears.
Use it for values that move around the screen, such as a licence plate that
shows up in a list on one screen and in a confirmation on the next.

Text rules need OCR: install the extra with `pip install .[ocr]` and install
Tesseract itself. Without it, text rules are skipped and a warning is printed
once per run; region rules are unaffected.

OCR is best-effort. A missed word is a real possibility on a low-resolution or
motion-blurred frame, so do not rely on a text rule alone for anything that must
not leave the building. Cover it with a region rule where you can.

### Checking your rules before a full run

```
whs-recorder redact-preview --image shot.png --redact redaction.json --out preview.png --label
```

`--label` outlines and names each masked area, which makes it obvious when a box
is off by a few percent. Turn it off for the real run, or set `"label": true` in
the config to keep the outlines in the delivered document.

## Before you share the document

* Open the document and look at every screenshot. The rules are geometry, not
  understanding: a screen you did not anticipate can put a name where no rule
  covers it.
* Check `steps.json` for the rules that actually ran. It records `"redaction":
  "none"` when the run had no rules, which is the usual cause of a leak.
* Your own step titles and notes go into the document verbatim. They are not
  redacted, and neither are the recorded values in the step text.
