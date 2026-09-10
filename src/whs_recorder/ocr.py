"""Reading the text off a screenshot.

OCR is optional: it needs `pytesseract` and a Tesseract install. Everything here
returns nothing at all when it is missing, and says so once, so a feature built
on it degrades instead of failing.
"""

from dataclasses import dataclass
from typing import List, Optional, Tuple

import cv2

DEFAULT_MIN_CONFIDENCE = 40.0

_WARNED = False


@dataclass
class TextLine:
    """A line of text found on screen, with the box it occupies."""

    text: str
    left: int
    top: int
    width: int
    height: int
    confidence: float = 0.0

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height

    @property
    def centre(self) -> Tuple[float, float]:
        return self.left + self.width / 2, self.top + self.height / 2

    def box(self) -> Tuple[int, int, int, int]:
        return self.left, self.top, self.width, self.height

    def contains(self, point: Tuple[float, float]) -> bool:
        x, y = point
        return self.left <= x <= self.right and self.top <= y <= self.bottom


def _warn_once(message: str) -> None:
    global _WARNED
    if not _WARNED:
        print(f"[ocr] {message}")
        _WARNED = True


def available() -> bool:
    """Whether OCR can run at all."""
    try:
        import pytesseract
    except ImportError:
        return False
    try:
        pytesseract.get_tesseract_version()
    except Exception:
        return False
    return True


def read(frame, min_confidence: float = DEFAULT_MIN_CONFIDENCE) -> List[TextLine]:
    """OCR a frame into words. Empty when OCR is unavailable."""
    if frame is None:
        return []

    try:
        import pytesseract
    except ImportError:
        _warn_once("pytesseract is not installed - text features are skipped.")
        return []

    try:
        data = pytesseract.image_to_data(
            cv2.cvtColor(frame, cv2.COLOR_BGR2RGB),
            output_type=pytesseract.Output.DICT,
        )
    except Exception as exc:  # tesseract binary missing, or an unreadable frame
        _warn_once(f"OCR unavailable ({exc}) - text features are skipped.")
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
            TextLine(
                text=text,
                left=int(data["left"][i]),
                top=int(data["top"][i]),
                width=int(data["width"][i]),
                height=int(data["height"][i]),
                confidence=confidence,
                )
        )
        words[-1].line_key = (
            data.get("block_num", [0] * (i + 1))[i],
            data.get("par_num", [0] * (i + 1))[i],
            data.get("line_num", [0] * (i + 1))[i],
        )
    return words


def group_lines(words: List[TextLine]) -> List[TextLine]:
    """Join words that share a line into one TextLine."""
    lines = {}
    for index, word in enumerate(words):
        key = getattr(word, "line_key", (0, 0, index))
        lines.setdefault(key, []).append(word)

    grouped = []
    for key in sorted(lines, key=lambda k: (lines[k][0].top, lines[k][0].left)):
        parts = sorted(lines[key], key=lambda w: w.left)
        left = min(w.left for w in parts)
        top = min(w.top for w in parts)
        right = max(w.right for w in parts)
        bottom = max(w.bottom for w in parts)
        grouped.append(
            TextLine(
                text=" ".join(w.text for w in parts),
                left=left,
                top=top,
                width=right - left,
                height=bottom - top,
                confidence=min(w.confidence for w in parts),
            )
        )
    return grouped


def read_lines(frame, min_confidence: float = DEFAULT_MIN_CONFIDENCE) -> List[TextLine]:
    """OCR a frame into lines of text."""
    return group_lines(read(frame, min_confidence))


def words_with_boxes(frame, min_confidence: float = DEFAULT_MIN_CONFIDENCE):
    """The shape the redaction rules want: (text, (x, y, w, h)) per word."""
    return [(word.text, word.box()) for word in read(frame, min_confidence)]
