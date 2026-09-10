"""The recorder's capture logic. The popups themselves need a display, so the
module keeps tkinter, mss and pynput out of its imports and this exercises the
part that decides which frame becomes the result screenshot."""

import threading

import numpy as np

from conftest import add_banner, make_screen

from whs_recorder.marker_recorder import _capture_result

GREEN = (0, 200, 0)
RED = (0, 0, 220)


def grabber(frames):
    """Hand out the frames in order, then repeat the last one."""
    state = {"i": 0}

    def grab():
        i = min(state["i"], len(frames) - 1)
        state["i"] += 1
        return frames[i]

    return grab


def test_the_frame_with_the_banner_wins():
    baseline = make_screen(seed=0)
    frames = [make_screen(seed=1), add_banner(make_screen(seed=2), GREEN), make_screen(seed=3)]

    frame, family = _capture_result(grabber(frames), baseline, 0.25, threading.Event(), sample_sec=0.01)

    assert family == "success"
    assert (frame[560:600, :, 1] > 120).mean() > 0.9


def test_an_error_banner_is_reported_as_such():
    baseline = make_screen(seed=0)
    frames = [make_screen(seed=1), add_banner(make_screen(seed=2), RED)]

    _, family = _capture_result(grabber(frames), baseline, 0.25, threading.Event(), sample_sec=0.01)

    assert family == "error"


def test_without_a_banner_the_last_frame_wins():
    """It is the screen the action left behind."""
    baseline = make_screen(seed=0)
    last = make_screen(seed=9)
    frames = [make_screen(seed=1), make_screen(seed=2), last]

    frame, family = _capture_result(grabber(frames), baseline, 0.06, threading.Event(), sample_sec=0.01)

    assert family == ""
    assert np.array_equal(frame, last)


def test_a_banner_already_on_screen_is_chrome_not_a_result():
    baseline = add_banner(make_screen(seed=0), GREEN, y1=0, y2=40)
    frames = [add_banner(make_screen(seed=1), GREEN, y1=0, y2=40)]

    _, family = _capture_result(grabber(frames), baseline, 0.05, threading.Event(), sample_sec=0.01)

    assert family == ""


def test_stopping_early_returns_what_was_captured():
    stop = threading.Event()
    stop.set()

    frame, family = _capture_result(grabber([make_screen()]), None, 5.0, stop, sample_sec=0.01)

    assert frame is None and family == ""


def test_a_grab_that_fails_ends_the_watch():
    frame, family = _capture_result(lambda: None, None, 5.0, threading.Event(), sample_sec=0.01)

    assert frame is None and family == ""


def test_the_window_is_respected():
    import time

    started = time.time()
    _capture_result(grabber([make_screen()]), None, 0.2, threading.Event(), sample_sec=0.02)

    assert 0.15 <= time.time() - started < 1.0
