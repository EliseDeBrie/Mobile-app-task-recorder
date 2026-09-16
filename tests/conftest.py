import os
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))


class FakeCapture:
    """Stands in for cv2.VideoCapture over an in-memory list of frames."""

    def __init__(self, frames, fps=10.0):
        self.frames = frames
        self.fps = fps
        self.pos = 0

    def set(self, prop, value):
        self.pos = int(value)
        return True

    def read(self):
        if 0 <= self.pos < len(self.frames):
            frame = self.frames[self.pos]
            self.pos += 1
            return True, frame.copy()
        return False, None

    def get(self, prop):
        return self.fps

    def release(self):
        pass


def make_screen(width=360, height=640, seed=0):
    """A textured frame that clears the sharpness and edge-density floors."""
    rng = np.random.default_rng(seed)
    frame = np.full((height, width, 3), 235, dtype=np.uint8)
    for row in range(20, height - 20, 24):
        frame[row:row + 8, 20:width - 20] = rng.integers(0, 90, size=3, dtype=np.uint8)
    return frame


def add_banner(frame, color, y1=560, y2=600):
    out = frame.copy()
    out[y1:y2, :] = color
    return out


#: Phrases a TclError uses when the machine cannot open a window at all, as
#: opposed to the code under test asking for something impossible.
NO_TOOLKIT = (
    "init.tcl",
    "display",
    "tcl wasn't installed",
    "can't find a usable",
)


def open_window(build):
    """Build a Tk window, or skip when this machine cannot open one.

    A machine with no display cannot open a window, and the Windows runner has
    been seen losing its Tcl install partway through a run. Neither says
    anything about the code under test, so both skip. Any other TclError is a
    real failure and is raised.

    The window is built directly rather than after a throwaway probe: every Tk
    root is another chance to meet that broken install, so there is no sense
    creating two where one will do.
    """
    tkinter = pytest.importorskip("tkinter")
    try:
        return build()
    except tkinter.TclError as exc:
        if any(sign in str(exc).lower() for sign in NO_TOOLKIT):
            pytest.skip(f"no windowing toolkit here: {exc}")
        raise


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


@pytest.fixture
def screen():
    return make_screen()
