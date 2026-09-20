# Privacy and redaction

This page is the privacy policy for WHS Task Recorder. The first part says what
the program does on your machine, in full. The rest is about the recordings
themselves: they routinely capture things a test document should not carry -
the signed-in worker, badge numbers, licence plates, customer names on a pick
list - and this page describes how to keep that material out of the generated
document.

## What the program does on your machine

WHS Task Recorder is an independent tool, published by its author on GitHub at
[github.com/EliseDeBrie/Mobile-app-task-recorder](https://github.com/EliseDeBrie/Mobile-app-task-recorder).
It is not affiliated with the vendors of the products it works alongside.

**Nothing leaves your machine.** The program has no network code. It does not
sign you in, does not phone home, sends no telemetry, no crash reports and no
usage figures, and never uploads a screenshot, a recording or a document. The
only way anything it made reaches another machine is you sending the file.

**What it captures, and when.** While a recording is running, and only then:

* It takes pictures of one rectangle of the screen - the one you drew around
  the warehouse app when the recording started. Nothing outside that rectangle
  is ever captured: not the rest of the desktop, not other windows, not a
  second monitor.
* It listens for mouse clicks and for a few keys, through the ordinary Windows
  input hooks, so that it knows when you tapped the app and when you pressed
  Enter. Only the position of a click and whether Enter, Ctrl or Shift is down
  are used. What you type is not recorded: no key text, no values, no
  passwords. What appears *on the screen* after you type is in the screenshot,
  which is why the redaction rules below exist.
* It reads the text on those screenshots with OCR to write the step sentences.
  That runs on your machine - the engine built into Windows, or a local copy of
  Tesseract - and nothing is sent anywhere to be read.

Press Stop and all of it stops. The program does not run in the background,
does not start with Windows and has no service.

**Where it writes.** Everything goes into the folder you chose in the launcher
(by default `Documents\WHS recordings`): the recording (`.json`), its
screenshots, the build folder and the Word document. The program keeps no
settings, no history and no copy of anything elsewhere. Delete the folder and
nothing of the recording remains.

**No account, no age gate, no advertising, no third parties.** There is nothing
to sign up for and nobody the program talks to. If you installed it from a
store, that store's own terms cover what the store records about the download;
the program itself adds nothing to that.

**Questions** go to the repository's issue tracker at the address above.

## What the tool stores

Everything stays on the machine that runs it. There is no telemetry, no upload
and no network call in any code path.

| Artefact | Written by | Contains |
| --- | --- | --- |
| the recording JSON | `whs-recorder mark` | Timestamps, the screen, action, control and value of each step, your titles and notes, the screen region being watched, and the screen-change score. No pixels. The screenshot names in it are read from the recording's own folder and nowhere else. |
| `<recording>_screenshots/*.png` | `whs-recorder mark` | The screenshots captured from the app region as you record. |
| `run_<stamp>/step_*.jpg` | `whs-recorder build` | The screenshots, after redaction. |
| `run_<stamp>/steps.json` | `whs-recorder build` | The per-step manifest: generated instructions, titles, notes, the screenshot file names, which rules were applied. |
| `run_<stamp>/<recording name>.docx` | `whs-recorder build` | The document, with the redacted screenshots embedded. |

The values you scan and type are part of the recording, and the generated steps
repeat them ("In the LP field, scan 'LP000123'"). Build with `--values example`
to replace them with "enter a value" wording, which keeps live data out of a
guide that will be shared widely.

Only the region you selected is ever captured. The rest of the desktop, other
windows, and a second monitor are never in frame.

OCR, where it is used to write the steps down for you, runs on this machine: the
engine built into Windows is an on-device API, and Tesseract is a local binary.
No screenshot is sent anywhere by either. What it reads can end
up in the recording as the screen, control and value of a step, so the same care
applies to those fields as to the screenshots.

At build time, redaction happens before an image is written, so the run folder
never holds an unredacted screenshot and the document cannot embed one.

The screenshots the **recorder** writes are a different matter: they are captured
as they appear, before any build-time rules exist. Pass `--redact` to
`whs-recorder mark` as well to have the rules applied as each one is written.
Without it, treat that folder as confidential, exactly like the source recording.

A screen recording, if you use one, is **not** redacted. It is your original
evidence, and it still holds everything that was on screen, including whatever
was outside the app region. Treat the MP4 as confidential, and share the
generated folder rather than the recording.

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
