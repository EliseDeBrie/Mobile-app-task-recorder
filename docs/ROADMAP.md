# Roadmap

## v0.1 — done
- Marker recording (manual / smart)
- Word evidence generation
- Basic screenshot filtering

## v0.2 — done
- Manual step labeling popup
- Redaction rules (fixed regions, plus OCR text patterns when Tesseract is present)
- Improved frame selection (result-banner / toast detection)
- `redact-preview` command for tuning rules against one screenshot
- Per-run `steps.json` manifest
- Headless test suite

## v0.3 — done
- Task Recorder recording model: subtasks, info steps, hidden steps, title and note annotations
- Generated step text, using Task Recorder's instruction-label resolution
- Preferred and example value wording (`--values`), and per-step overrides
- Task guide document style, alongside the original evidence style
- `preview` command for reading the guide text before building
- Recorder gestures for subtasks and info steps
- Backwards compatible with pre-v0.3 markers files

## v0.4 — done
- Region capture: drag out the app window the way Greenshot does, name it by window title, or type its coordinates
- Screenshots taken straight from the app region at each step, so a separate screen recording is optional
- Result banner captured live, judged against the screen from before the action
- The step popup is placed beside the app, never over it
- Every Tk window runs on one owner thread
- Video builds crop to the region when the recording covers the whole screen

## v0.5 — done
- Each step records the screen it happened on, printed in the guide when it changes
- The popup arrives filled in, where OCR is available: screen from the title bar, control from the label above the tap, value from the text that appeared
- Shared OCR reader behind both the redaction rules and the suggestions

## v0.6 — done
- Runs with no administrator rights anywhere: per-user Python, `pip install --user`, and the OCR engine already in Windows
- Second OCR engine, Windows OCR, preferred over Tesseract because it installs nothing
- Portable Tesseract supported through `--tesseract`, an environment variable, or a known folder
- `check` command reporting what is present, what is missing, and the fix for each
- `check` reads a test image through the live engine, so an OCR install is proven rather than assumed

## v0.7 — done
- A capture session per thread, since steps are detected on one thread and the result watched on another
- Screenshots read and written through Python, so a path with accents works
- The recording is saved after every step and written atomically, so a crash costs nothing
- Documents keep the accents in their name; the manifest names files rather than full paths
- A failure a consultant can act on is a plain message, not a stack trace
- The dialog thread reports why it cannot open a window instead of hanging
- `check` tells a package that is missing apart from one that will not load

## v0.8 — done
- A launcher window, so the program is useful without a terminal: name it, record, build, all from one place
- Packaged to a single .exe by CI, with nothing to install on the machine that runs it
- Windows CI: the tests and the setup check now run on Windows on every push, which is what would have caught the OCR call that reached a user

## v0.9 — done
- Recording no longer interrupts: each step is written down from what the screen says, with nothing to answer
- A recorder bar beside the app: the step count, the last step taken, and a stop button
- A review window listing every recorded step with its screenshot, for correcting the wording, leaving a step out, reordering and deleting
- `review` command, and the same window opening by itself when a recording finishes
- `--ask-each-step` for anyone who would rather name each step as they take it

## v0.9.4 — done
- A Store package (MSIX) built by CI beside the `.exe`, so the program can be published where it is signed for free
- Screenshot paths in a recording confined to the recording's own folder
- Pinned build dependencies, a vulnerability audit on every CI run, Dependabot, and actions pinned by commit
- A privacy policy that says everything the program does, and a security page

## v0.10
- Template customization (house styles, cover page)
- Listing on the Store, once the app name is reserved (see docs/STORE.md)

## Future
- Batch processing
- D365-aware heuristics
- Optional AI step description generation
