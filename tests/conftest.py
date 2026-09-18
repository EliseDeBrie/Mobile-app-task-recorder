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


def _failed_starting_tk(error: BaseException) -> bool:
    """Whether this TclError means the machine cannot start Tk at all.

    Matching on the wording does not work: the same broken runner has produced
    "couldn't read file ... init.tcl" one day and 'invalid command name
    "tcl_findLibrary"' the next, and guessing the next phrase is a game with no
    end. Where the error came from is the reliable signal.

    Every failure of this kind happens inside `Tk.__init__`, while the Tcl
    interpreter itself is being created: no display to connect to, or an
    install whose own startup script is missing. Our widget code cannot reach
    that point, so a TclError raised there is the machine's problem, and a
    TclError raised anywhere else - a bad option on a widget, say - is ours and
    must still fail.
    """
    import tkinter

    frames = []
    traceback = error.__traceback__
    while traceback is not None:
        frames.append(traceback.tb_frame)
        traceback = traceback.tb_next

    return any(
        frame.f_code.co_name == "__init__"
        # Tk is the interpreter; Toplevel and the widgets are not subclasses of
        # it, so this does not catch a failure in a window's contents.
        and isinstance(frame.f_locals.get("self"), tkinter.Tk)
        for frame in frames
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
        if _failed_starting_tk(exc):
            pytest.skip(f"this machine cannot start Tk: {exc}")
        raise


@pytest.fixture(autouse=True)
def free_windows_on_this_thread():
    """Collect garbage after every test, on the main thread.

    Tk widgets refer to one another in cycles, so a window a test closed is
    freed by the cyclic collector - on whichever thread next triggers it. In
    a suite with threads coming and going that was a background thread, and
    Tk aborted the whole run: "Tcl_AsyncDelete: async handler deleted by the
    wrong thread". Freeing here keeps every window on the thread that made it.
    """
    yield
    import gc

    gc.collect()


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


@pytest.fixture
def screen():
    return make_screen()
