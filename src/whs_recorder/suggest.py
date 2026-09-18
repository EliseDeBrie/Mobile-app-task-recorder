"""Reading the step off the screen, so it can be written down without asking.

Task Recorder never has to ask what was clicked: every control reports itself.
Here there is only a picture, so the next best thing is to read it. Where OCR is
available this offers three answers:

* the **screen** you were on, taken from the title band at the top of the
  screen as it was when you tapped,
* the **control** you used, taken from the text at or just above the tap on
  that same screen,
* the **value** that appeared, taken from the text that was not there before.

They are guesses, and the review window is where they are corrected. Without
OCR every one of them comes back empty and the step is written down bare.
"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable, List, Optional, Sequence, Tuple

from . import ocr
from .ocr import TextLine

TITLE_BAND = 0.16      # fraction of the screen height a title bar can occupy
NEAR_PX = 40           # how far above a tap a field label can sit
VALUE_NEAR_PX = 64     # how far from a tap the value it entered can appear
MIN_TEXT = 2           # shorter than this is OCR noise, not a label


@dataclass
class Suggestion:
    """What the screen appears to say about a step."""

    screen: str = ""
    control: str = ""
    value: str = ""

    def is_empty(self) -> bool:
        return not (self.screen or self.control or self.value)


def clean(text: str) -> str:
    """Tidy a line of OCR output into something a step can use."""
    text = " ".join((text or "").split())
    return text.rstrip(":.").strip()


def _usable(line: TextLine) -> bool:
    return len(clean(line.text)) >= MIN_TEXT


def screen_title(lines: Sequence[TextLine], height: int, band: float = TITLE_BAND) -> str:
    """The most prominent line in the title band at the top of the screen."""
    band_px = max(int(height * band), 1)
    candidates = [text_line for text_line in lines if text_line.top < band_px and _usable(text_line)]
    if not candidates:
        return ""
    # A title is the biggest text up there; ties go to the highest line.
    best = max(candidates, key=lambda text_line: (text_line.height, -text_line.top))
    return clean(best.text)


def control_at(
    lines: Sequence[TextLine],
    point: Optional[Tuple[float, float]],
    skip: str = "",
    near: int = NEAR_PX,
) -> str:
    """The control the tap landed on, or the label sitting just above it."""
    if point is None:
        return ""

    usable = [text_line for text_line in lines if _usable(text_line) and clean(text_line.text) != skip]
    if not usable:
        return ""

    x, y = point

    # A label sitting just above the tap names the field, and the text inside
    # the field is its value rather than its name, so the label is asked first.
    # A label sits a short hop above the input it names, and the input spans the
    # width of a narrow screen, so the gap decides and the tap only has to be
    # right of where the label starts. Testing the tap against the label's own
    # span missed every wide field; ignoring position entirely let empty space
    # claim the nearest button.
    above = [
        text_line for text_line in usable
        if text_line.bottom <= y and y - text_line.bottom <= near and x >= text_line.left - near
    ]
    if above:
        return clean(min(above, key=lambda text_line: y - text_line.bottom).text)

    # Otherwise the text under the finger: a button carries its own label.
    hits = [text_line for text_line in usable if text_line.contains(point)]
    if hits:
        return clean(min(hits, key=lambda text_line: text_line.width * text_line.height).text)

    # Nothing close enough. An empty box beats a wrong guess the reader has to
    # notice and undo.
    return ""


def value_appeared(
    before: Sequence[TextLine],
    after: Sequence[TextLine],
    point: Optional[Tuple[float, float]] = None,
    skip: Sequence[str] = (),
    within: int = VALUE_NEAR_PX,
) -> str:
    """Text that is on screen now and was not before: what was entered or scanned.

    Only text near the tap counts. Plenty else changes at the same moment - a
    result banner most of all - and none of it is the value that was entered.
    """
    previous = {clean(text_line.text) for text_line in before}
    skipped = {s for s in skip if s}

    fresh = [
        text_line for text_line in after
        if _usable(text_line) and clean(text_line.text) not in previous and clean(text_line.text) not in skipped
    ]
    if not fresh:
        return ""

    if point is None:
        return clean(fresh[0].text)

    x, y = point
    near_tap = [text_line for text_line in fresh if abs(text_line.centre[1] - y) <= within]
    if not near_tap:
        return ""

    near_tap.sort(key=lambda text_line: abs(text_line.centre[1] - y) + abs(text_line.centre[0] - x) / 4)
    return clean(near_tap[0].text)


def near_gaps(height: int) -> Tuple[int, int]:
    """Scale the label and value distances to the screen being captured."""
    return max(int(height * 0.06), 24), max(int(height * 0.10), 40)


def suggest_step(
    after,
    point: Optional[Tuple[float, float]] = None,
    before=None,
    reader: Optional[Callable[[object], List[TextLine]]] = None,
) -> Suggestion:
    """Read a screenshot and propose the screen, control and value for a step."""
    if after is None:
        return Suggestion()

    reader = reader or ocr.read_lines

    # Both frames are read at once: OCR is the slow part of writing a step down.
    before_lines: List[TextLine] = []
    if before is None:
        lines = reader(after)
    else:
        with ThreadPoolExecutor(max_workers=2) as pool:
            after_job = pool.submit(reader, after)
            before_job = pool.submit(reader, before)
            lines = after_job.result()
            before_lines = before_job.result()

    if not lines and not before_lines:
        return Suggestion()

    height = after.shape[0]
    label_gap, value_gap = near_gaps(height)

    # The screen and the control are read off the frame from *before* the
    # tap: that is the screen the person was on and the button under their
    # finger. A tap on "Inbound" is followed by a different screen, and
    # reading the control off that one found whatever had landed at the same
    # spot, or nothing. Without a before frame the after frame has to do.
    acted_on = before_lines if before is not None else lines
    screen = screen_title(acted_on, height)
    control = control_at(acted_on, point, skip=screen, near=label_gap)

    value = ""
    if before is not None:
        value = value_appeared(
            before_lines, lines, point, skip=(screen, control), within=value_gap
        )

    return Suggestion(screen=screen, control=control, value=value)
