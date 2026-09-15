"""The window you get when you double-click the program.

Everything this tool does is available from the command line, but a consultant
on a customer's machine should not have to open a terminal to record a process.
This is that window: name the recording, press a button, work through the
process on the handheld, press stop.

Recording runs as a separate process rather than inside this one. Tk keeps a
per-thread interpreter, the recorder opens windows of its own on its own
thread, and two interpreters in one process is the hazard that makes a dialog
render but never answer. A separate process sidesteps it entirely, and a crash
while recording leaves this window standing.
"""

import os
import queue
import subprocess
import sys
import threading
from typing import List, Optional

from . import __version__

WINDOW_TITLE = f"WHS Task Recorder {__version__}"
DEFAULT_FOLDER = os.path.join(os.path.expanduser("~"), "Documents", "WHS recordings")


def command_prefix() -> List[str]:
    """How to invoke this tool again as a command.

    Packaged as a single executable, `sys.executable` is that executable and it
    is handed the arguments directly. Running from a checkout, it is the Python
    interpreter, which needs the module spelled out.
    """
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, "-m", "whs_recorder.cli"]


def command_environment() -> dict:
    """The environment for that command.

    Run from a checkout rather than an install, the child interpreter has no
    way to find this package unless it is told where it lives.
    """
    environment = dict(os.environ)
    if getattr(sys, "frozen", False):
        return environment

    package_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    existing = environment.get("PYTHONPATH", "")
    if package_parent not in existing.split(os.pathsep):
        environment["PYTHONPATH"] = (
            f"{package_parent}{os.pathsep}{existing}" if existing else package_parent
        )
    return environment


class Launcher:
    """One window: check the setup, record a process, build the document."""

    def __init__(self):
        import tkinter as tk
        from tkinter import ttk

        self.tk = tk
        self.ttk = ttk
        self.messages: "queue.Queue[str]" = queue.Queue()
        self.running: Optional[subprocess.Popen] = None

        self.root = tk.Tk()
        self.root.title(WINDOW_TITLE)
        self.root.minsize(640, 520)

        self._build_widgets()
        self.root.after(100, self._drain)

    # ----------------------------------------------------------------- widgets

    def _build_widgets(self) -> None:
        tk, ttk = self.tk, self.ttk

        frame = ttk.Frame(self.root, padding=14)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)

        row = 0
        ttk.Label(frame, text="Record a process", font=("Segoe UI", 11, "bold")).grid(
            row=row, column=0, columnspan=3, sticky="w"
        )

        row += 1
        ttk.Label(frame, text="Name:").grid(row=row, column=0, sticky="w", pady=(8, 0))
        self.name = tk.StringVar(value="Receive a purchase order line")
        ttk.Entry(frame, textvariable=self.name).grid(
            row=row, column=1, columnspan=2, sticky="ew", pady=(8, 0)
        )

        row += 1
        ttk.Label(frame, text="Description:").grid(row=row, column=0, sticky="w", pady=(6, 0))
        self.description = tk.StringVar()
        ttk.Entry(frame, textvariable=self.description).grid(
            row=row, column=1, columnspan=2, sticky="ew", pady=(6, 0)
        )

        row += 1
        ttk.Label(frame, text="Save in:").grid(row=row, column=0, sticky="w", pady=(6, 0))
        self.folder = tk.StringVar(value=DEFAULT_FOLDER)
        ttk.Entry(frame, textvariable=self.folder).grid(row=row, column=1, sticky="ew", pady=(6, 0))
        ttk.Button(frame, text="Browse", command=self._pick_folder).grid(
            row=row, column=2, sticky="e", padx=(6, 0), pady=(6, 0)
        )

        row += 1
        self.record_button = ttk.Button(frame, text="Start recording", command=self._record)
        self.record_button.grid(row=row, column=1, sticky="w", pady=(12, 0))
        ttk.Label(
            frame,
            text="Drag a box around the app, then work through the process.  Ctrl+Shift+End stops.",
            foreground="#555",
        ).grid(row=row + 1, column=1, columnspan=2, sticky="w")

        row += 2
        ttk.Separator(frame).grid(row=row, column=0, columnspan=3, sticky="ew", pady=14)

        row += 1
        ttk.Label(frame, text="Build the document", font=("Segoe UI", 11, "bold")).grid(
            row=row, column=0, columnspan=3, sticky="w"
        )

        row += 1
        ttk.Label(frame, text="Recording:").grid(row=row, column=0, sticky="w", pady=(8, 0))
        self.recording_file = tk.StringVar()
        ttk.Entry(frame, textvariable=self.recording_file).grid(
            row=row, column=1, sticky="ew", pady=(8, 0)
        )
        ttk.Button(frame, text="Browse", command=self._pick_recording).grid(
            row=row, column=2, sticky="e", padx=(6, 0), pady=(8, 0)
        )

        row += 1
        ttk.Label(frame, text="Style:").grid(row=row, column=0, sticky="w", pady=(6, 0))
        self.style = tk.StringVar(value="task-guide")
        ttk.Combobox(
            frame, textvariable=self.style, values=["task-guide", "evidence"],
            state="readonly", width=18,
        ).grid(row=row, column=1, sticky="w", pady=(6, 0))

        row += 1
        self.build_button = ttk.Button(frame, text="Build document", command=self._build)
        self.build_button.grid(row=row, column=1, sticky="w", pady=(12, 0))

        row += 1
        ttk.Separator(frame).grid(row=row, column=0, columnspan=3, sticky="ew", pady=14)

        row += 1
        buttons = ttk.Frame(frame)
        buttons.grid(row=row, column=0, columnspan=3, sticky="w")
        ttk.Button(buttons, text="Check setup", command=self._check).grid(row=0, column=0)
        ttk.Button(buttons, text="Open folder", command=self._open_folder).grid(
            row=0, column=1, padx=(8, 0)
        )

        row += 1
        frame.rowconfigure(row, weight=1)
        self.log = tk.Text(frame, height=10, wrap="word", state="disabled",
                           background="#f7f7f7", relief="flat")
        self.log.grid(row=row, column=0, columnspan=3, sticky="nsew", pady=(12, 0))

        self._say(f"{WINDOW_TITLE}. Press 'Check setup' to confirm this machine is ready.")

    # ------------------------------------------------------------------ helpers

    def _say(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text.rstrip() + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _drain(self) -> None:
        """Move output from the worker thread into the log."""
        try:
            while True:
                self._say(self.messages.get_nowait())
        except queue.Empty:
            pass
        self.root.after(100, self._drain)

    def _busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self.record_button.configure(state=state)
        self.build_button.configure(state=state)

    def recording_path(self) -> str:
        from .utils import safe_filename

        name = safe_filename(self.name.get(), "recording")
        return os.path.join(self.folder.get(), f"{name}.json")

    def _pick_folder(self) -> None:
        from tkinter import filedialog

        chosen = filedialog.askdirectory(initialdir=self.folder.get() or os.path.expanduser("~"))
        if chosen:
            self.folder.set(chosen)

    def _pick_recording(self) -> None:
        from tkinter import filedialog

        chosen = filedialog.askopenfilename(
            initialdir=self.folder.get(), filetypes=[("Recordings", "*.json"), ("All files", "*.*")]
        )
        if chosen:
            self.recording_file.set(chosen)

    def _open_folder(self) -> None:
        folder = self.folder.get()
        if not os.path.isdir(folder):
            self._say(f"Nothing there yet: {folder}")
            return
        if os.name == "nt":
            os.startfile(folder)  # noqa: S606 - the point is to open a folder
        else:
            subprocess.Popen(["xdg-open", folder])

    # ------------------------------------------------------------------ actions

    def _run(self, args: List[str], done: str) -> None:
        """Run the tool as a command and stream its output into the log."""
        self._busy(True)

        def worker():
            try:
                process = subprocess.Popen(
                    command_prefix() + args,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    env=command_environment(),
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                self.running = process
                for line in process.stdout:
                    self.messages.put(line)
                process.wait()
                self.messages.put(done if process.returncode == 0 else "Stopped with an error.")
            except Exception as exc:
                self.messages.put(f"Could not run it: {exc}")
            finally:
                self.running = None
                self.root.after(0, lambda: self._busy(False))

        threading.Thread(target=worker, daemon=True).start()

    def _check(self) -> None:
        self._say("\nChecking this machine...")
        self._run(["check"], "Check finished.")

    def _record(self) -> None:
        if not self.name.get().strip():
            self._say("Give the recording a name first.")
            return

        os.makedirs(self.folder.get(), exist_ok=True)
        path = self.recording_path()
        self.recording_file.set(path)

        self._say(f"\nRecording to {path}")
        self._say("Drag a box around the warehouse app. Ctrl+Shift+End stops and saves.")
        self._run(
            ["mark", "--out", path, "--name", self.name.get(), "--description", self.description.get()],
            "Recording saved. Press 'Build document' when you are ready.",
        )

    def _build(self) -> None:
        path = self.recording_file.get() or self.recording_path()
        if not os.path.isfile(path):
            self._say(f"No recording at {path}. Record one first, or browse to it.")
            return

        out = os.path.join(os.path.dirname(path), "guide")
        self._say(f"\nBuilding from {os.path.basename(path)}...")
        self._run(
            ["build", "--markers", path, "--out", out, "--style", self.style.get(), "--skip-loading"],
            "Document written. Press 'Open folder' to find it.",
        )

    def run(self) -> None:
        self.root.mainloop()


def hide_console() -> None:
    """Hide the console window the packaged program was started from.

    The program is built as a console application so that the commands it runs
    for itself have somewhere to write. Double-clicked, though, that console is
    an empty black window sitting behind the launcher, so it is hidden as soon
    as the launcher opens. Started from a terminal there is nothing to hide,
    and the commands print as usual.
    """
    if os.name != "nt" or not getattr(sys, "frozen", False):
        return

    try:
        import ctypes

        console = ctypes.windll.kernel32.GetConsoleWindow()
        if console:
            ctypes.windll.user32.ShowWindow(console, 0)  # SW_HIDE
    except Exception:
        pass  # a missing console is not a reason to refuse to start


def main() -> None:
    """Open the launcher window."""
    hide_console()
    Launcher().run()


if __name__ == "__main__":
    main()
