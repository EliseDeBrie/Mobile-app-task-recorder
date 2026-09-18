"""One thread owns every Tk window the recorder opens.

Tk keeps a per-thread interpreter and a module-level default root, so creating a
fresh root on each worker thread misbehaves: the second window appears on screen
but never processes its events, and the popup that looks ready to fill in is
dead. The recorder's steps are detected on timer threads, so the windows cannot
simply be opened from wherever a step happens to be noticed.

`DialogHost` settles it. It owns one hidden root and runs every dialog there as
a `Toplevel`, while the thread that asked for the dialog blocks until the answer
comes back.

Which thread owns the root matters more than it looks. Tk objects call into the
interpreter when they are garbage collected, and the interpreter itself is torn
down by whichever thread drops the last reference to it. When that is not the
thread that created it, Tcl aborts the process: "async handler deleted by the
wrong thread". Running the root on a background thread left the main thread to
do exactly that at exit, and the recorder crashed on every Stop. So the root
lives on the main thread, which is where Tk wants it, and the recorder's own
waiting happens inside the pump rather than beside it. The background-thread
form is kept for callers that have no main loop to give up.

There is a second way to the same abort, and it is subtler. Tk widgets refer to
each other in cycles - a window to its children, each child to its master - so
a closed window is not freed when the last name for it goes, but by the cyclic
garbage collector, which runs on whichever thread happens to allocate at the
wrong moment. A result-watcher thread finishing was enough. So every window is
collected here, on the owning thread, the moment it closes: `collect_windows`
is called after each dialog and on close, and costs a few milliseconds.
"""

import contextlib
import gc
import queue
import threading
from typing import Any, Callable, Optional

PUMP_MS = 40
START_TIMEOUT_SEC = 20.0
WATCH_INTERVAL_SEC = 0.5


def collect_windows() -> int:
    """Free closed windows now, on this thread, rather than on whichever
    thread the garbage collector next happens to run on. See the module
    docstring for why that thread must be the one that owns the windows."""
    return gc.collect()


class DialogHost:
    """Runs dialogs on a single thread and hands their results back."""

    def __init__(self):
        self._requests: "queue.Queue[tuple]" = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._owner: Optional[int] = None  # ident of the thread that owns the root
        self._ready = threading.Event()
        self._stopping = threading.Event()
        self._root = None
        self._failure: Optional[BaseException] = None

    # -------------------------------------------------------- on this thread

    def open(self) -> "DialogHost":
        """Create the root on the calling thread, which becomes its owner.

        Dialogs asked for from this thread run at once; from any other thread
        they wait for `serve` to run them.
        """
        if self._root is not None:
            return self
        try:
            self._root = self._make_root()
        except BaseException as exc:  # no display, no tkinter, a broken install
            raise RuntimeError(f"Cannot open windows: {exc}") from exc
        self._owner = threading.get_ident()
        self._stopping.clear()
        self._ready.set()
        return self

    def serve(self, until: Callable[[], bool], poll_ms: int = 100) -> None:
        """Run the dialog loop on the owning thread until `until()` is true.

        This is the recorder's wait: it sits here while taps are noticed on
        other threads, running whatever dialogs they ask for, and returns when
        the session is over.
        """
        self._require_owner("serve")
        root = self._root

        def pump():
            self._run_requests()
            if self._stopping.is_set() or until():
                root.quit()
                return
            root.after(poll_ms, pump)

        root.after(0, pump)
        root.mainloop()

    def close(self) -> None:
        """Destroy the root, on the thread that owns it."""
        if self._root is None:
            return
        self._require_owner("close")
        with contextlib.suppress(Exception):
            self._root.destroy()
        self._root = None
        self._owner = None
        self._ready.clear()
        collect_windows()

    # ------------------------------------------------------ on its own thread

    def start(self) -> "DialogHost":
        """Start a dialog thread, or raise if its windowing toolkit is missing."""
        if self._thread is not None or self._root is not None:
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
        """End `serve`, or the dialog thread, whichever is running."""
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
        """Run `dialog(root)` on the owning thread and wait for what it returns."""
        if self._root is None and self._thread is None:
            self.start()

        if threading.get_ident() == self._owner:
            # Already on the owning thread: waiting on the queue would wait
            # for ourselves. The dialog can simply be run.
            try:
                return dialog(self._root)
            finally:
                collect_windows()

        if self._thread is not None and not self._thread.is_alive():
            raise RuntimeError("The dialog thread is gone; no window can be opened.")

        done = threading.Event()
        box = {}

        self._requests.put((dialog, box, done))
        while not done.wait(timeout=WATCH_INTERVAL_SEC if timeout is None else timeout):
            if timeout is not None:
                break
            # Waiting for a person to answer takes as long as it takes, but a
            # dialog thread that has died must not leave the caller hanging.
            if self._thread is not None and not self._thread.is_alive():
                raise RuntimeError("The dialog thread stopped before the window was answered.")
            if self._thread is None and self._root is None:
                raise RuntimeError("The windows were closed before the dialog was answered.")

        if "error" in box:
            raise box["error"]
        return box.get("value")

    # -------------------------------------------------------------------- inner

    def _require_owner(self, what: str) -> None:
        if self._root is None:
            raise RuntimeError(f"Cannot {what}: the windows are not open.")
        if threading.get_ident() != self._owner:
            raise RuntimeError(f"Cannot {what} from a thread that does not own the windows.")

    def _make_root(self):
        """The hidden window every dialog is a child of."""
        import tkinter as tk

        root = tk.Tk()
        root.withdraw()
        return root

    def _run_requests(self) -> None:
        try:
            while True:
                dialog, box, done = self._requests.get_nowait()
                try:
                    box["value"] = dialog(self._root)
                except BaseException as exc:  # hand it to the caller, keep the thread
                    box["error"] = exc
                finally:
                    collect_windows()
                    done.set()
        except queue.Empty:
            pass

    def _run(self) -> None:
        try:
            self._root = self._make_root()
        except BaseException as exc:  # no display, no tkinter, a broken install
            self._failure = exc
            return
        finally:
            self._ready.set()
        self._owner = threading.get_ident()

        def pump():
            self._run_requests()
            if self._stopping.is_set():
                self._root.quit()
                return
            self._root.after(PUMP_MS, pump)

        self._root.after(PUMP_MS, pump)
        self._root.mainloop()

        with contextlib.suppress(Exception):
            self._root.destroy()
        self._root = None
        self._owner = None

        # Whatever still refers to the interpreter - a closure the pump held,
        # a widget a dialog returned - must be collected here, on the thread
        # that made it. Left for another thread's garbage collector, the
        # interpreter is deleted from the wrong thread and Tcl aborts the
        # process, at some unrelated moment later on.
        collect_windows()


def wait_for(root, window) -> None:
    """Pump events until `window` closes. Must run on the owning thread."""
    try:
        # A window that is not on screen yet cannot be grabbed, and the grab is
        # only a courtesy: dialogs are asked for one at a time regardless.
        window.update_idletasks()
        window.grab_set()
    except Exception:
        pass
    root.wait_window(window)
