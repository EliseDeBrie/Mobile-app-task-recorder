"""Shared helpers used by the recorder and the evidence builder."""

import os
from typing import Optional

import cv2
import numpy as np


def ensure_dir(path: str) -> None:
    """Create a directory if it does not exist. Empty paths are ignored."""
    if path:
        os.makedirs(path, exist_ok=True)


def ensure_parent_dir(file_path: str) -> None:
    """Create the folder that will hold `file_path` (no-op for bare filenames)."""
    ensure_dir(os.path.dirname(os.path.abspath(file_path)))


def to_gray(frame: np.ndarray) -> np.ndarray:
    if frame.ndim == 2:
        return frame
    return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)


def sharpness(frame: np.ndarray) -> float:
    """Variance of the Laplacian: low on motion-blurred / mid-transition frames."""
    return float(cv2.Laplacian(to_gray(frame), cv2.CV_64F).var())


def edge_density(frame: np.ndarray) -> float:
    """Fraction of edge pixels: low on blank or still-loading screens."""
    g = cv2.GaussianBlur(to_gray(frame), (3, 3), 0)
    e = cv2.Canny(g, 60, 140)
    return float((e > 0).mean())


def quality_score(frame: np.ndarray) -> float:
    """Combined legibility score used to rank candidate frames."""
    return sharpness(frame) * (1.0 + 10.0 * edge_density(frame))


def mean_abs_diff(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.mean(np.abs(a.astype(np.float32) - b.astype(np.float32))))


def get_frame_at(cap, frame_index: int) -> Optional[np.ndarray]:
    cap.set(cv2.CAP_PROP_POS_FRAMES, max(int(frame_index), 0))
    ok, frame = cap.read()
    return frame if ok else None


def iter_frames(cap, start_index: int, end_index: int):
    """Yield (index, frame) from start to end inclusive, seeking only once.

    Reading forward is both faster and more thorough than seeking per frame, so
    short scans (such as the window after a marker) see every frame.
    """
    index = max(int(start_index), 0)
    cap.set(cv2.CAP_PROP_POS_FRAMES, index)
    while index <= int(end_index):
        ok, frame = cap.read()
        if not ok:
            return
        yield index, frame
        index += 1


def is_letter_key(key, letter: str) -> bool:
    """True when a pynput key is the given letter, modifier applied or not.

    Ctrl+S arrives as the control character \x13 rather than "s" on some
    platforms, and as a virtual key code on others.
    """
    char = getattr(key, "char", None)
    if char:
        if char.lower() == letter:
            return True
        if len(char) == 1 and ord(char) == ord(letter) - 96:  # Ctrl+letter
            return True
    return getattr(key, "vk", None) == ord(letter.upper())
