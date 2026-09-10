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

## v0.4
- Desktop UI
- Packaging to single .exe
- Template customization (house styles, cover page)

## Future
- Batch processing
- D365-aware heuristics
- Optional AI step description generation
