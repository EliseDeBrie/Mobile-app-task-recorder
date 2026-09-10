"""Frame selection: pick the most legible screenshot for a step, and find the
frame that actually shows the result message.

WHS mobile confirms an action with a coloured banner (green for success, red for
an error, amber for a warning) that stays on screen for well under a second. A
fixed "grab the frame 0.6s later" rule misses it whenever the device or the
network is slower than usual, so `choose_result_frame` scans the window after
the marker and prefers a frame where such a banner is actually visible.
"""

from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

import cv2
import numpy as np

from .utils import combine_quality, edge_density, get_frame_at, iter_frames, quality_score, sharpness

# OpenCV hue ranges (0..179) for the banner colours WHS mobile uses.
TOAST_FAMILIES = {
    "success": ((35, 85),),
    "error": ((0, 10), (170, 179)),
    "warning": ((11, 34),),
}


@dataclass
class ToastDetection:
    """A coloured banner found in a frame."""

    found: bool = False
    family: str = ""
    score: float = 0.0
    y1: int = 0
    y2: int = 0

    @property
    def height(self) -> int:
        return max(self.y2 - self.y1, 0)


@dataclass
class FrameChoice:
    """A chosen frame plus how it was chosen."""

    frame: Optional[np.ndarray]
    mode: str
    offset: float = 0.0
    toast: Optional[ToastDetection] = None

    @property
    def has_toast(self) -> bool:
        return self.toast is not None and self.toast.found


def _row_coverage(hsv: np.ndarray, hue_ranges, min_sat: int, min_val: int) -> np.ndarray:
    """Fraction of pixels per row that carry one of the given hues."""
    hue, sat, val = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    saturated = (sat >= min_sat) & (val >= min_val)

    in_hue = np.zeros(hue.shape, dtype=bool)
    for low, high in hue_ranges:
        in_hue |= (hue >= low) & (hue <= high)

    return (in_hue & saturated).mean(axis=1)


def _longest_run(flags: np.ndarray) -> Tuple[int, int]:
    """Return (start, end_exclusive) of the longest True run, or (0, 0)."""
    best = (0, 0)
    start = None
    for i, flag in enumerate(flags):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            if i - start > best[1] - best[0]:
                best = (start, i)
            start = None
    if start is not None and len(flags) - start > best[1] - best[0]:
        best = (start, len(flags))
    return best


def detect_toast(
    frame: np.ndarray,
    baseline: Optional[np.ndarray] = None,
    min_row_coverage: float = 0.5,
    min_band_frac: float = 0.02,
    max_band_frac: float = 0.35,
    min_sat: int = 90,
    min_val: int = 60,
) -> ToastDetection:
    """Look for a wide, coloured, horizontal banner in `frame`.

    `baseline` is the frame captured at the marker itself. A banner that is
    equally present in the baseline is static chrome (the app's own header bar),
    not a result message, so it is discounted.
    """
    if frame is None or frame.ndim != 3:
        return ToastDetection()

    height = frame.shape[0]
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    base_hsv = cv2.cvtColor(baseline, cv2.COLOR_BGR2HSV) if baseline is not None else None
    if base_hsv is not None and base_hsv.shape[:2] != hsv.shape[:2]:
        base_hsv = None

    best = ToastDetection()

    for family, hue_ranges in TOAST_FAMILIES.items():
        coverage = _row_coverage(hsv, hue_ranges, min_sat, min_val)
        y1, y2 = _longest_run(coverage >= min_row_coverage)
        band = y2 - y1
        if band < max(int(min_band_frac * height), 2) or band > max_band_frac * height:
            continue

        score = float(coverage[y1:y2].mean())

        if base_hsv is not None:
            base_coverage = _row_coverage(base_hsv, hue_ranges, min_sat, min_val)
            base_score = float(base_coverage[y1:y2].mean())
            # Fully static band -> not a message. Partly changed -> reduced score.
            score *= float(np.clip(1.0 - base_score / max(score, 1e-6), 0.0, 1.0))

        if score > best.score:
            best = ToastDetection(found=score > 0.05, family=family, score=score, y1=y1, y2=y2)

    return best


def best_frame_near(
    cap,
    fps: float,
    t_sec: float,
    window_sec: float,
    sharp_min: float,
    edge_min: float,
) -> Optional[np.ndarray]:
    """Highest-quality frame within `window_sec` of `t_sec` that clears both floors."""
    center = int(t_sec * fps)
    radius = max(int(window_sec * fps), 1)
    step = max(int(fps // 4), 1)

    best = None
    best_score = -1.0

    for fi in range(max(center - radius, 0), center + radius + 1, step):
        frame = get_frame_at(cap, fi)
        if frame is None:
            continue

        # Both measurements are a full pass over the frame, so they are taken
        # once and reused rather than recomputed to score the frame.
        sharp = sharpness(frame)
        if sharp < sharp_min:
            continue
        edges = edge_density(frame)
        if edges < edge_min:
            continue

        score = combine_quality(sharp, edges)
        if score > best_score:
            best_score = score
            best = frame

    return best


def choose_frame(cap, fps: float, t_sec: float) -> FrameChoice:
    """Pick a legible frame near `t_sec`, relaxing the quality floors as needed."""
    frame = best_frame_near(cap, fps, t_sec, window_sec=1.8, sharp_min=65, edge_min=0.012)
    if frame is not None:
        return FrameChoice(frame, "strict")

    frame = best_frame_near(cap, fps, t_sec, window_sec=2.5, sharp_min=35, edge_min=0.008)
    if frame is not None:
        return FrameChoice(frame, "relaxed")

    frame = get_frame_at(cap, int(t_sec * fps))
    if frame is not None:
        return FrameChoice(frame, "exact")

    return FrameChoice(None, "none")


def choose_result_frame(
    cap,
    fps: float,
    t_sec: float,
    baseline: Optional[np.ndarray] = None,
    offsets: Sequence[float] = (0.6, 1.2),
    window_sec: float = 2.5,
    use_toast_detection: bool = True,
    min_offset_sec: float = 0.15,
) -> FrameChoice:
    """Find the frame that shows the outcome of the action marked at `t_sec`.

    With toast detection on, the whole window after the marker is scanned and the
    frame with the clearest result banner wins. When no banner is found (or the
    feature is off) this falls back to the fixed `offsets`, ranked by legibility.
    """
    if use_toast_detection:
        best: Optional[FrameChoice] = None
        best_key = (0.0, -1.0)

        first = int((t_sec + min_offset_sec) * fps)
        last = int((t_sec + window_sec) * fps)
        for fi, frame in iter_frames(cap, first, last):
            toast = detect_toast(frame, baseline)
            if not toast.found:
                continue
            key = (toast.score, quality_score(frame))
            if key > best_key:
                best_key = key
                best = FrameChoice(frame, "toast", round(fi / fps - t_sec, 2), toast)

        if best is not None:
            return best

    best_choice: Optional[FrameChoice] = None
    best_quality = -1.0
    for off in offsets:
        choice = choose_frame(cap, fps, t_sec + off)
        if choice.frame is None:
            continue
        score = quality_score(choice.frame)
        if score > best_quality:
            best_quality = score
            best_choice = FrameChoice(choice.frame, choice.mode, off, None)

    return best_choice or FrameChoice(None, "none")
