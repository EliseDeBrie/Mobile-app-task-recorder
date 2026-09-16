"""The test helpers themselves.

`open_window` decides whether a window test runs or skips. Getting that wrong
in either direction is expensive: too eager and every machine without a display
fails, too generous and a real widget bug is skipped over and never seen.
"""

import pytest

from conftest import open_window


def test_a_window_that_opens_is_handed_back():
    assert open_window(lambda: "a window") == "a window"


def test_a_machine_with_no_display_skips():
    tkinter = pytest.importorskip("tkinter")

    def no_display():
        raise tkinter.TclError("no display name and no $DISPLAY environment variable")

    with pytest.raises(BaseException) as caught:
        open_window(no_display)
    assert "Skipped" in type(caught.value).__name__


def test_a_runner_that_lost_its_tcl_install_skips():
    # Seen on windows-latest: the hosted Python's Tcl disappears partway
    # through a run, which is the runner's problem and not the code's.
    tkinter = pytest.importorskip("tkinter")

    def broken_install():
        raise tkinter.TclError(
            "Can't find a usable init.tcl in the following directories:"
        )

    with pytest.raises(BaseException) as caught:
        open_window(broken_install)
    assert "Skipped" in type(caught.value).__name__


def test_a_mistake_in_the_widgets_is_still_a_failure():
    tkinter = pytest.importorskip("tkinter")

    def bad_option():
        raise tkinter.TclError('unknown option "-wrapength"')

    with pytest.raises(tkinter.TclError):
        open_window(bad_option)
