"""The dialog host. Tk itself needs a display, so this covers the parts that
decide whether a window can be opened at all, and what happens when it cannot:
a recorder that silently hangs is worse than one that says why it stopped."""

import threading

import pytest

from whs_recorder.dialogs import DialogHost


class BrokenHost(DialogHost):
    """A host whose windowing toolkit refuses to start."""

    def _run(self):
        self._failure = RuntimeError("no display name and no $DISPLAY")
        self._ready.set()


class DeadHost(DialogHost):
    """A host whose thread stops without answering."""

    def _run(self):
        self._ready.set()


def test_a_host_that_cannot_open_windows_says_so():
    with pytest.raises(RuntimeError, match="Cannot open windows"):
        BrokenHost().start()


def test_asking_a_dead_host_raises_instead_of_hanging():
    """Waiting forever for a window that will never appear looks like a freeze."""
    host = DeadHost()
    host.start()
    host._thread.join(timeout=2)

    with pytest.raises(RuntimeError, match="dialog thread"):
        host.ask(lambda root: "never answered")


def test_a_failed_start_can_be_retried():
    host = BrokenHost()
    with pytest.raises(RuntimeError):
        host.start()

    assert host._thread is None  # not left half-started


def test_asking_returns_what_the_dialog_returned(monkeypatch):
    """The queue and hand-back, without Tk: the dialog is called and its answer arrives."""
    host = DialogHost()
    answered = threading.Event()

    class FakeRoot:
        def after(self, _ms, callback):
            threading.Timer(0.01, callback).start()

        def mainloop(self):
            answered.wait(timeout=5)

        def quit(self):
            answered.set()

        def withdraw(self):
            pass

        def destroy(self):
            pass

    monkeypatch.setattr(host, "_make_root", lambda: FakeRoot())

    host.start()
    try:
        assert host.ask(lambda root: 42) == 42
        with pytest.raises(ValueError, match="bad step"):
            host.ask(lambda root: (_ for _ in ()).throw(ValueError("bad step")))
    finally:
        host.stop()


# ------------------------------------------------- the root on this thread


def test_the_root_can_live_on_the_calling_thread():
    from conftest import open_window

    host = open_window(lambda: DialogHost().open())
    try:
        # From the owning thread a dialog runs at once, with the root.
        assert host.ask(lambda root: root is host._root) is True
    finally:
        host.close()
        assert host._root is None


def test_serving_runs_dialogs_asked_for_from_other_threads():
    """The recorder waits inside `serve`; its timer threads ask for windows."""
    from conftest import open_window

    host = open_window(lambda: DialogHost().open())
    answers = []
    over = threading.Event()

    def elsewhere():
        answers.append(host.ask(lambda root: "answered on the owner's thread"))
        over.set()

    threading.Thread(target=elsewhere, daemon=True).start()
    try:
        host.serve(until=over.is_set, poll_ms=10)
    finally:
        host.close()

    assert answers == ["answered on the owner's thread"]


def test_serving_ends_when_told_to_stop():
    from conftest import open_window

    host = open_window(lambda: DialogHost().open())
    threading.Timer(0.05, host.stop).start()
    try:
        host.serve(until=lambda: False, poll_ms=10)  # returns only because of stop()
    finally:
        host.close()


def test_serving_from_another_thread_is_refused():
    from conftest import open_window

    host = open_window(lambda: DialogHost().open())
    errors = []

    def elsewhere():
        try:
            host.serve(until=lambda: True)
        except RuntimeError as exc:
            errors.append(str(exc))

    thread = threading.Thread(target=elsewhere)
    thread.start()
    thread.join(timeout=2)
    host.close()

    assert errors and "does not own" in errors[0]


def test_a_dialog_is_freed_on_the_owning_thread_before_anyone_else_can():
    """A closed window is cyclic garbage, and the cyclic collector runs on
    whichever thread next triggers it. The owner collects first."""
    import gc

    from conftest import open_window

    host = open_window(lambda: DialogHost().open())
    try:
        def open_and_close(root):
            import tkinter as tk

            window = tk.Toplevel(root)
            tk.Label(window, text="gone in a moment").pack()
            window.destroy()
            return "closed"

        assert host.ask(open_and_close) == "closed"
        # Nothing left for another thread's collector to find.
        assert gc.collect() == 0
    finally:
        host.close()
