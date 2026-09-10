"""Reading the text off a screenshot.

Two engines can do it, and neither needs administrator rights:

* **Windows OCR** is part of Windows 10 and 11. Nothing is installed for it -
  the WinRT wheels are a normal user-level `pip install` - and it is the
  default where it works.
* **Tesseract** is used when Windows OCR is unavailable. Its usual installer
  wants an administrator, so the path to a portable copy can be given instead,
  with `--tesseract`, the `WHS_TESSERACT` environment variable, or by unpacking
  it into `%LOCALAPPDATA%\\whs-recorder\\tesseract`.

With neither, everything here returns nothing and says so once, so the features
built on it go quiet rather than failing.
"""

import os
import shutil
import sys
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

import cv2

DEFAULT_MIN_CONFIDENCE = 40.0

WINDOWS = "windows"
TESSERACT = "tesseract"
BACKENDS = (WINDOWS, TESSERACT)

#: Where a portable Tesseract is looked for, after the explicit settings.
PORTABLE_DIRS = (
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "whs-recorder", "tesseract"),
    os.path.join(os.path.dirname(os.path.abspath(sys.argv[0] or ".")), "tesseract"),
)

_state: Dict[str, object] = {"tesseract_path": "", "prefer": "", "warned": False}


@dataclass
class TextLine:
    """A run of text found on screen, with the box it occupies."""

    text: str
    left: int
    top: int
    width: int
    height: int
    confidence: float = 0.0
    line_key: Tuple[int, int, int] = (0, 0, 0)

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


@dataclass
class BackendStatus:
    """What one engine can do on this machine, and how to fix it if it cannot."""

    name: str
    ready: bool
    detail: str = ""
    remedy: str = ""


def configure(tesseract_path: str = "", prefer: str = "") -> None:
    """Point at a Tesseract of your own, or force one engine over the other."""
    if tesseract_path:
        _state["tesseract_path"] = tesseract_path
    if prefer:
        _state["prefer"] = prefer.strip().lower()
    _state["warned"] = False


def _warn_once(message: str) -> None:
    if not _state["warned"]:
        print(f"[ocr] {message}")
        _state["warned"] = True


# --------------------------------------------------------------------- windows


def winrt_modules():
    """The WinRT namespaces this needs, from whichever package supplies them.

    `winsdk` bundled every namespace and has wheels up to Python 3.11; the
    `winrt-*` packages split them per namespace and cover later versions. Both
    expose the same generated API, so either will do.
    """
    import importlib

    for root in ("winrt", "winsdk"):
        try:
            return {
                "system": importlib.import_module(f"{root}.system"),
                "ocr": importlib.import_module(f"{root}.windows.media.ocr"),
                "imaging": importlib.import_module(f"{root}.windows.graphics.imaging"),
                "streams": importlib.import_module(f"{root}.windows.storage.streams"),
            }
        except ImportError:
            continue
    return None


def windows_engine(modules=None):
    """The Windows OCR engine for the user's languages, or None."""
    modules = modules or winrt_modules()
    if modules is None:
        return None

    try:
        # Each worker thread needs an apartment before it touches WinRT.
        system = modules["system"]
        init = getattr(system, "init_apartment", None)
        if init is not None:
            try:
                init(system.MTA)
            except Exception:
                pass  # already initialised for this thread
        return modules["ocr"].OcrEngine.try_create_from_user_profile_languages()
    except Exception:
        return None


def _read_windows(frame, min_confidence: float) -> List[TextLine]:
    """Read a frame with the OCR engine built into Windows."""
    import asyncio

    modules = winrt_modules()
    if modules is None:
        return []

    BitmapPixelFormat = modules["imaging"].BitmapPixelFormat
    SoftwareBitmap = modules["imaging"].SoftwareBitmap
    Buffer = modules["streams"].Buffer

    engine = windows_engine(modules)
    if engine is None:
        return []

    height, width = frame.shape[:2]
    data = cv2.cvtColor(frame, cv2.COLOR_BGR2BGRA).tobytes()

    buffer = Buffer(len(data))
    buffer.length = len(data)
    with memoryview(buffer) as view:
        view[:] = data

    bitmap = SoftwareBitmap.create_copy_from_buffer(buffer, BitmapPixelFormat.BGRA8, width, height)
    result = asyncio.run(engine.recognize_async(bitmap))

    lines: List[TextLine] = []
    for index, line in enumerate(result.lines or []):
        words = list(line.words or [])
        if not words:
            continue
        for word in words:
            rect = word.bounding_rect
            lines.append(
                TextLine(
                    text=word.text,
                    left=int(rect.x),
                    top=int(rect.y),
                    width=int(rect.width),
                    height=int(rect.height),
                    # Windows OCR reports only what it is sure of, and gives no
                    # score of its own, so every word clears any threshold.
                    confidence=100.0,
                    line_key=(0, 0, index),
                )
            )
    return lines


# ------------------------------------------------------------------- tesseract


def tesseract_path() -> str:
    """Where Tesseract is, checking the explicit settings before the PATH."""
    explicit = str(_state.get("tesseract_path") or "") or os.environ.get("WHS_TESSERACT", "")
    if explicit and os.path.isfile(explicit):
        return explicit

    name = "tesseract.exe" if os.name == "nt" else "tesseract"
    for folder in PORTABLE_DIRS:
        if not folder:
            continue
        candidate = os.path.join(folder, name)
        if os.path.isfile(candidate):
            return candidate

    return shutil.which("tesseract") or ""


def _read_tesseract(frame, min_confidence: float) -> List[TextLine]:
    """Read a frame with Tesseract."""
    try:
        import pytesseract
    except ImportError:
        return []

    path = tesseract_path()
    if path:
        pytesseract.pytesseract.tesseract_cmd = path

    data = pytesseract.image_to_data(
        cv2.cvtColor(frame, cv2.COLOR_BGR2RGB),
        output_type=pytesseract.Output.DICT,
    )

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
                line_key=(
                    int(data.get("block_num", [0])[i]),
                    int(data.get("par_num", [0])[i]),
                    int(data.get("line_num", [0])[i]),
                ),
            )
        )
    return words


# ---------------------------------------------------------------------- choice


READERS: Dict[str, Callable[[object, float], List[TextLine]]] = {
    WINDOWS: _read_windows,
    TESSERACT: _read_tesseract,
}


WINDOWS_REMEDY = 'pip install --user ".[ocr-windows]" (Windows only, no administrator needed)'


def windows_status() -> BackendStatus:
    if winrt_modules() is None:
        return BackendStatus(
            WINDOWS, False, "the WinRT packages are not installed", WINDOWS_REMEDY,
        )
    if windows_engine() is None:
        return BackendStatus(
            WINDOWS, False, "Windows has no OCR language pack for your languages",
            "add a language pack under Settings > Time & language, or use Tesseract",
        )
    return BackendStatus(WINDOWS, True, "built into Windows, nothing to install")


def tesseract_status() -> BackendStatus:
    try:
        import pytesseract  # noqa: F401
    except ImportError:
        return BackendStatus(
            TESSERACT, False, "the pytesseract package is not installed",
            "pip install --user pytesseract, then point --tesseract at a portable Tesseract",
        )

    path = tesseract_path()
    if not path:
        return BackendStatus(
            TESSERACT, False, "no tesseract binary found",
            "unpack a portable Tesseract into %LOCALAPPDATA%\\whs-recorder\\tesseract, "
            "or pass --tesseract with its path",
        )
    return BackendStatus(TESSERACT, True, f"using {path}")


def statuses() -> List[BackendStatus]:
    """What each engine can do here. Used by the `check` command."""
    return [windows_status(), tesseract_status()]


def active_backend() -> str:
    """The engine that will be used, or an empty string when there is none."""
    preferred = str(_state.get("prefer") or os.environ.get("WHS_OCR", "")).strip().lower()
    if preferred in ("none", "off"):
        return ""

    order = [preferred] if preferred in BACKENDS else list(BACKENDS)
    for name in order:
        status = windows_status() if name == WINDOWS else tesseract_status()
        if status.ready:
            return name
    return ""


def available() -> bool:
    """Whether OCR can run at all."""
    return bool(active_backend())


def read_words(frame, min_confidence: float = DEFAULT_MIN_CONFIDENCE) -> List[TextLine]:
    """OCR a frame into words. Empty when no engine is available."""
    if frame is None:
        return []

    backend = active_backend()
    if not backend:
        _warn_once(
            "no OCR engine available - text features are skipped. "
            "Run 'whs-recorder check' to see what is missing."
        )
        return []

    try:
        return READERS[backend](frame, min_confidence)
    except Exception as exc:  # a broken install should not stop a recording
        _warn_once(f"the {backend} OCR engine failed ({exc}) - text features are skipped.")
        return []


#: Kept for callers that read word boxes rather than lines.
read = read_words


def group_lines(words: List[TextLine]) -> List[TextLine]:
    """Join words that share a line into one TextLine."""
    lines: Dict[Tuple[int, int, int], List[TextLine]] = {}
    for index, word in enumerate(words):
        lines.setdefault(getattr(word, "line_key", (0, 0, index)), []).append(word)

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
    return group_lines(read_words(frame, min_confidence))


def words_with_boxes(frame, min_confidence: float = DEFAULT_MIN_CONFIDENCE):
    """The shape the redaction rules want: (text, (x, y, w, h)) per word."""
    return [(word.text, word.box()) for word in read_words(frame, min_confidence)]
