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

import queue
import threading
from typing import Any, Callable, Optional

PUMP_MS = 40


class DialogHost:
    """Runs dialogs on a single thread and hands their results back."""

    def __init__(self):
        self._requests: "queue.Queue[tuple]" = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()
        self._stopping = threading.Event()
        self._root = None

    # ---------------------------------------------------------------- lifecycle

    def start(self) -> "DialogHost":
        if self._thread is not None:
            return self
        self._thread = threading.Thread(target=self._run, daemon=True, name="whs-dialogs")
        self._thread.start()
        self._ready.wait(timeout=10.0)
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

        done = threading.Event()
        box = {}

        self._requests.put((dialog, box, done))
        done.wait(timeout=timeout)

        if "error" in box:
            raise box["error"]
        return box.get("value")

    # -------------------------------------------------------------------- inner

    def _run(self) -> None:
        import tkinter as tk

        self._root = tk.Tk()
        self._root.withdraw()
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

        try:
            self._root.destroy()
        except Exception:
            pass
        self._root = None


def wait_for(root, window) -> None:
    """Pump events until `window` closes. Must run on the dialog thread."""
    window.grab_set()
    root.wait_window(window)
