"""Redaction rules applied to every screenshot before it reaches the Word document.

Two kinds of rule are supported:

* **Region rules** always mask the same part of the screen (a title bar carrying
  a user name, a badge number in the status line, ...). They need no OCR and are
  the reliable option for a fixed device layout.
* **Text rules** mask any word matching a regular expression, wherever it is on
  screen. They need OCR (``pytesseract`` plus a Tesseract install). When OCR is
  unavailable the text rules are skipped and a single warning is printed, so a
  missing OCR install can never silently drop a *region* rule.

Configuration is a JSON file, for example::

    {
      "default_mode": "box",
      "label": true,
      "regions": [
        {"name": "user", "box": [0.0, 0.0, 1.0, 0.06]},
        {"name": "badge", "box": [820, 40, 1080, 96], "units": "absolute", "mode": "blur"}
      ],
      "text_patterns": [
        {"name": "licence plate", "pattern": "LP[0-9]{6,}", "mode": "pixelate"}
      ]
    }
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

MODES = ("box", "blur", "pixelate")
DEFAULT_MODE = "box"

_OCR_WARNED = False


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(int(value), high))


def _normalise_mode(mode: Optional[str], fallback: str) -> str:
    mode = (mode or fallback or DEFAULT_MODE).strip().lower()
    if mode not in MODES:
        raise ValueError(f"Unknown redaction mode: {mode!r} (expected one of {', '.join(MODES)})")
    return mode


def _mask_region(frame: np.ndarray, box: Tuple[int, int, int, int], mode: str) -> None:
    """Mask `box` in-place. `box` is (x1, y1, x2, y2) in pixels."""
    x1, y1, x2, y2 = box
    if x2 <= x1 or y2 <= y1:
        return

    if mode == "box":
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 0), thickness=-1)
        return

    roi = frame[y1:y2, x1:x2]
    if roi.size == 0:
        return

    if mode == "blur":
        h, w = roi.shape[:2]
        k = max(int(min(h, w) / 3) | 1, 9)
        frame[y1:y2, x1:x2] = cv2.GaussianBlur(roi, (k, k), 0)
        return

    # pixelate
    h, w = roi.shape[:2]
    small = cv2.resize(roi, (max(w // 12, 1), max(h // 12, 1)), interpolation=cv2.INTER_AREA)
    frame[y1:y2, x1:x2] = cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST)


def _draw_label(frame: np.ndarray, box: Tuple[int, int, int, int], text: str) -> None:
    x1, y1, x2, y2 = box
    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), thickness=2)
    baseline_y = y1 + 18 if y1 + 18 < frame.shape[0] else max(y1 - 6, 12)
    cv2.putText(
        frame,
        text,
        (x1 + 4, baseline_y),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        (0, 0, 255),
        1,
        cv2.LINE_AA,
    )


@dataclass
class RegionRule:
    """A fixed rectangle that is masked on every screenshot."""

    name: str
    box: Tuple[float, float, float, float]
    units: str = "relative"
    mode: str = DEFAULT_MODE

    def resolve(self, width: int, height: int) -> Tuple[int, int, int, int]:
        x1, y1, x2, y2 = self.box
        if self.units == "relative":
            x1, x2 = x1 * width, x2 * width
            y1, y2 = y1 * height, y2 * height
        x1, x2 = sorted((_clamp(round(x1), 0, width), _clamp(round(x2), 0, width)))
        y1, y2 = sorted((_clamp(round(y1), 0, height), _clamp(round(y2), 0, height)))
        return x1, y1, x2, y2

    @staticmethod
    def from_dict(d: Dict[str, Any], default_mode: str) -> "RegionRule":
        box = d.get("box")
        if not isinstance(box, Sequence) or len(box) != 4:
            raise ValueError(f"Region rule {d.get('name', '?')!r} needs a 'box' of [x1, y1, x2, y2]")
        units = (d.get("units") or "relative").strip().lower()
        if units not in ("relative", "absolute"):
            raise ValueError(f"Unknown units {units!r} (expected 'relative' or 'absolute')")
        if units == "relative" and any(not (0.0 <= float(v) <= 1.0) for v in box):
            raise ValueError(
                f"Region rule {d.get('name', '?')!r} uses relative units, so the box must be 0..1"
            )
        return RegionRule(
            name=str(d.get("name") or "region"),
            box=tuple(float(v) for v in box),
            units=units,
            mode=_normalise_mode(d.get("mode"), default_mode),
        )


@dataclass
class TextRule:
    """A regular expression matched against OCR output and masked wherever it hits."""

    name: str
    pattern: str
    mode: str = DEFAULT_MODE
    padding: int = 3
    ignore_case: bool = True

    def compiled(self) -> "re.Pattern[str]":
        flags = re.IGNORECASE if self.ignore_case else 0
        return re.compile(self.pattern, flags)

    @staticmethod
    def from_dict(d: Dict[str, Any], default_mode: str) -> "TextRule":
        pattern = d.get("pattern")
        if not pattern:
            raise ValueError(f"Text rule {d.get('name', '?')!r} needs a 'pattern'")
        rule = TextRule(
            name=str(d.get("name") or "text"),
            pattern=str(pattern),
            mode=_normalise_mode(d.get("mode"), default_mode),
            padding=int(d.get("padding", 3)),
            ignore_case=bool(d.get("ignore_case", True)),
        )
        rule.compiled()  # fail fast on a bad regex
        return rule


@dataclass
class RedactionConfig:
    regions: List[RegionRule] = field(default_factory=list)
    text_patterns: List[TextRule] = field(default_factory=list)
    default_mode: str = DEFAULT_MODE
    label: bool = False
    ocr_min_confidence: float = 40.0

    def is_empty(self) -> bool:
        return not self.regions and not self.text_patterns

    def describe(self) -> str:
        parts = []
        if self.regions:
            parts.append(f"{len(self.regions)} region rule(s)")
        if self.text_patterns:
            parts.append(f"{len(self.text_patterns)} text rule(s)")
        return ", ".join(parts) if parts else "no rules"

    def apply(self, frame: np.ndarray) -> np.ndarray:
        """Return a redacted copy of `frame`. The input is never modified."""
        if frame is None or self.is_empty():
            return frame

        out = frame.copy()
        height, width = out.shape[:2]

        for rule in self.regions:
            box = rule.resolve(width, height)
            _mask_region(out, box, rule.mode)
            if self.label:
                _draw_label(out, box, rule.name)

        if self.text_patterns:
            for rule, box in self._text_boxes(frame, width, height):
                _mask_region(out, box, rule.mode)
                if self.label:
                    _draw_label(out, box, rule.name)

        return out

    def _text_boxes(self, frame, width, height):
        words = _ocr_words(frame, self.ocr_min_confidence)
        matchers = [(rule, rule.compiled()) for rule in self.text_patterns]
        for text, (x, y, w, h) in words:
            for rule, matcher in matchers:
                if not matcher.search(text):
                    continue
                pad = rule.padding
                box = (
                    _clamp(x - pad, 0, width),
                    _clamp(y - pad, 0, height),
                    _clamp(x + w + pad, 0, width),
                    _clamp(y + h + pad, 0, height),
                )
                yield rule, box
                break

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "RedactionConfig":
        default_mode = _normalise_mode(d.get("default_mode"), DEFAULT_MODE)
        return RedactionConfig(
            regions=[RegionRule.from_dict(r, default_mode) for r in d.get("regions", [])],
            text_patterns=[TextRule.from_dict(r, default_mode) for r in d.get("text_patterns", [])],
            default_mode=default_mode,
            label=bool(d.get("label", False)),
            ocr_min_confidence=float(d.get("ocr_min_confidence", 40.0)),
        )


def load_redaction_config(path: Optional[str]) -> Optional[RedactionConfig]:
    """Load a redaction config, or return None when no path is given."""
    if not path:
        return None
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return RedactionConfig.from_dict(data)


def _ocr_words(frame, min_confidence: float) -> List[Tuple[str, Tuple[int, int, int, int]]]:
    """OCR the frame into (text, (x, y, w, h)) tuples. Empty when OCR is unavailable."""
    global _OCR_WARNED
    try:
        import pytesseract
    except ImportError:
        if not _OCR_WARNED:
            print("[redaction] pytesseract is not installed - text rules are skipped.")
            _OCR_WARNED = True
        return []

    try:
        data = pytesseract.image_to_data(
            cv2.cvtColor(frame, cv2.COLOR_BGR2RGB),
            output_type=pytesseract.Output.DICT,
        )
    except Exception as exc:  # tesseract binary missing or unreadable frame
        if not _OCR_WARNED:
            print(f"[redaction] OCR unavailable ({exc}) - text rules are skipped.")
            _OCR_WARNED = True
        return []

    words = []
    for i, text in enumerate(data.get("text", [])):
        text = (text or "").strip()
        if not text:
            continue
        try:
            confidence = float(data["conf"][i])
        except (KeyError, TypeError, ValueError):
            confidence = -1.0
        if confidence < min_confidence:
            continue
        words.append(
            (text, (int(data["left"][i]), int(data["top"][i]), int(data["width"][i]), int(data["height"][i])))
        )
    return words
