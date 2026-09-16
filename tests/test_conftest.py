"""The test helpers themselves.

`open_window` decides whether a window test runs or skips. Getting that wrong
in either direction is expensive: too strict and every machine without a
display fails, too generous and a real widget bug is skipped over and never
seen. It has already been wrong once - it matched on the wording of the error,
and the next broken runner used different wording - so both directions are
pinned down here.
"""

import pytest

from conftest import open_window


def test_a_window_that_opens_is_handed_back():
    assert open_window(lambda: "a window") == "a window"


def test_a_machine_that_cannot_start_tk_skips(monkeypatch):
    """The Windows runner, whose Tcl install went missing mid-run."""
    tk = pytest.importorskip("tkinter")
    import _tkinter

    def no_interpreter(*_args, **_kwargs):
        raise tk.TclError('invalid command name "tcl_findLibrary"')

    monkeypatch.setattr(_tkinter, "create", no_interpreter)

    with pytest.raises(BaseException) as caught:
        open_window(tk.Tk)
    assert "Skipped" in type(caught.value).__name__


def test_a_machine_with_no_display_skips(monkeypatch):
    tk = pytest.importorskip("tkinter")
    import _tkinter

    def no_display(*_args, **_kwargs):
        raise tk.TclError("no display name and no $DISPLAY environment variable")

    monkeypatch.setattr(_tkinter, "create", no_display)

    with pytest.raises(BaseException) as caught:
        open_window(tk.Tk)
    assert "Skipped" in type(caught.value).__name__


def test_a_mistake_in_the_widgets_is_still_a_failure():
    """A real bug in a window's contents must never be quietly skipped."""
    tk = pytest.importorskip("tkinter")
    opened = []

    def build_a_broken_window():
        root = tk.Tk()
        opened.append(root)
        tk.Label(root, nosuchoption=1)  # the kind of mistake that must fail
        return root

    try:
        with pytest.raises(tk.TclError):
            open_window(build_a_broken_window)
    finally:
        for root in opened:
            root.destroy()
