"""One thread owns every Tk window the recorder opens.

Tk keeps a per-thread interpreter and a module-level default root, so creating a
fresh root on each worker thread misbehaves: the second window appears on screen
but never processes its events, and the popup that looks ready to fill in is
dead. The recorder's steps are detected on timer threads, so the windows cannot
simply live on the main thread either.

`DialogHost` settles it. It owns a hidden root on a thread of its own and runs
every dialog there as a `Toplevel`, while the thread that asked for the dialog
blocks until the answer comes back.
"""

import contextlib
import queue
import threading
from typing import Any, Callable, Optional

PUMP_MS = 40
START_TIMEOUT_SEC = 20.0
WATCH_INTERVAL_SEC = 0.5


class DialogHost:
    """Runs dialogs on a single thread and hands their results back."""

    def __init__(self):
        self._requests: "queue.Queue[tuple]" = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()
        self._stopping = threading.Event()
        self._root = None
        self._failure: Optional[BaseException] = None

    # ---------------------------------------------------------------- lifecycle

    def start(self) -> "DialogHost":
        """Start the dialog thread, or raise if its windowing toolkit is missing."""
        if self._thread is not None:
            return self

        self._thread = threading.Thread(target=self._run, daemon=True, name="whs-dialogs")
        self._thread.start()

        if not self._ready.wait(timeout=START_TIMEOUT_SEC):
            self._thread = None
            raise RuntimeError("The dialog thread did not start within 20 seconds.")
        if self._failure is not None:
            self._thread = None
            raise RuntimeError(f"Cannot open windows: {self._failure}") from self._failure
        return self

    def stop(self) -> None:
        self._stopping.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None

    def __enter__(self) -> "DialogHost":
        return self.start()

    def __exit__(self, *_exc) -> None:
        self.stop()

    # ------------------------------------------------------------------- asking

    def ask(self, dialog: Callable[[Any], Any], timeout: Optional[float] = None) -> Any:
        """Run `dialog(root)` on the dialog thread and wait for what it returns."""
        if self._thread is None:
            self.start()
        if not self._thread.is_alive():
            raise RuntimeError("The dialog thread is gone; no window can be opened.")

        done = threading.Event()
        box = {}

        self._requests.put((dialog, box, done))
        while not done.wait(timeout=WATCH_INTERVAL_SEC if timeout is None else timeout):
            if timeout is not None:
                break
            # Waiting for a person to answer takes as long as it takes, but a
            # dialog thread that has died must not leave the caller hanging.
            if not self._thread.is_alive():
                raise RuntimeError("The dialog thread stopped before the window was answered.")

        if "error" in box:
            raise box["error"]
        return box.get("value")

    # -------------------------------------------------------------------- inner

    def _make_root(self):
        """The hidden window every dialog is a child of."""
        import tkinter as tk

        root = tk.Tk()
        root.withdraw()
        return root

    def _run(self) -> None:
        try:
            self._root = self._make_root()
        except BaseException as exc:  # no display, no tkinter, a broken install
            self._failure = exc
            return
        finally:
            self._ready.set()

        def pump():
            try:
                while True:
                    dialog, box, done = self._requests.get_nowait()
                    try:
                        box["value"] = dialog(self._root)
                    except BaseException as exc:  # hand it to the caller, keep the thread
                        box["error"] = exc
                    finally:
                        done.set()
            except queue.Empty:
                pass

            if self._stopping.is_set():
                self._root.quit()
                return
            self._root.after(PUMP_MS, pump)

        self._root.after(PUMP_MS, pump)
        self._root.mainloop()

        with contextlib.suppress(Exception):
            self._root.destroy()
        self._root = None


def wait_for(root, window) -> None:
    """Pump events until `window` closes. Must run on the dialog thread."""
    try:
        # A window that is not on screen yet cannot be grabbed, and the grab is
        # only a courtesy: dialogs are asked for one at a time regardless.
        window.update_idletasks()
        window.grab_set()
    except Exception:
        pass
    root.wait_window(window)
