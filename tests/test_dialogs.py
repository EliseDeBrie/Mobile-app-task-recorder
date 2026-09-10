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
