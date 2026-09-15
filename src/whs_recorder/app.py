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

import contextlib
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
        self.root.minsize(600, 460)
        self.root.geometry("700x800")

        self._build_widgets()
        self.root.after(100, self._drain)

    # ----------------------------------------------------------------- widgets

    def _use_native_theme(self) -> None:
        """Look like a Windows program rather than a 1990s X application."""
        style = self.ttk.Style()
        for candidate in ("vista", "winnative", "clam"):
            if candidate in style.theme_names():
                style.theme_use(candidate)
                break

        family = "Segoe UI" if os.name == "nt" else "DejaVu Sans"
        style.configure(".", font=(family, 10))
        style.configure("Heading.TLabel", font=(family, 13, "bold"))
        style.configure("Title.TLabel", font=(family, 17, "bold"))
        style.configure("Field.TLabel", font=(family, 10, "bold"))
        style.configure("Hint.TLabel", font=(family, 9), foreground="#5c5c5c")
        style.configure("Banner.TFrame", background="#1f3864")
        style.configure("BannerTitle.TLabel", background="#1f3864", foreground="white",
                        font=(family, 17, "bold"))
        style.configure("BannerText.TLabel", background="#1f3864", foreground="#c9d4ea",
                        font=(family, 10))
        style.configure("Go.TButton", font=(family, 11, "bold"), padding=(18, 9))
        self.font_family = family

    def _field(self, parent, label: str, hint: str, initial: str = "", browse=None):
        """A labelled box with a line underneath saying what it is for."""
        tk, ttk = self.tk, self.ttk

        ttk.Label(parent, text=label, style="Field.TLabel").pack(anchor="w", pady=(10, 2))

        row = ttk.Frame(parent)
        row.pack(fill="x")
        variable = tk.StringVar(value=initial)
        entry = ttk.Entry(row, textvariable=variable)
        entry.pack(side="left", fill="x", expand=True, ipady=3)
        if browse is not None:
            ttk.Button(row, text="Browse...", command=browse, width=11).pack(side="left", padx=(8, 0))

        ttk.Label(parent, text=hint, style="Hint.TLabel", wraplength=560, justify="left").pack(
            anchor="w", pady=(2, 0)
        )
        return variable

    def _build_widgets(self) -> None:
        tk, ttk = self.tk, self.ttk
        self._use_native_theme()

        banner = ttk.Frame(self.root, style="Banner.TFrame", padding=(18, 14))
        banner.pack(fill="x")
        ttk.Label(banner, text="WHS Task Recorder", style="BannerTitle.TLabel").pack(anchor="w")
        ttk.Label(
            banner,
            text="Record what you do in the warehouse app, and turn it into a Word document.",
            style="BannerText.TLabel",
        ).pack(anchor="w", pady=(4, 0))

        # The buttons and the log are pinned to the bottom, and the form above
        # them scrolls. A laptop screen is shorter than this form, and controls
        # that fall off the bottom of a window are controls nobody finds.
        footer = ttk.Frame(self.root, padding=(18, 10))
        footer.pack(side="bottom", fill="both")

        scroller = ttk.Frame(self.root)
        scroller.pack(side="top", fill="both", expand=True)

        canvas = tk.Canvas(scroller, highlightthickness=0, borderwidth=0)
        bar = ttk.Scrollbar(scroller, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=bar.set)
        canvas.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")

        body = ttk.Frame(canvas, padding=(18, 14))
        held = canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(held, width=e.width))
        canvas.bind_all(
            "<MouseWheel>", lambda e: canvas.yview_scroll(int(-e.delta / 120), "units")
        )

        # ---------------------------------------------------------- record
        record = ttk.LabelFrame(body, text="  Step 1  Record the process  ", padding=(14, 8, 14, 14))
        record.pack(fill="x")

        self.name = self._field(
            record,
            "What is this process called?",
            "This becomes the title of the document. For example: Receive a purchase order line.",
            initial="",
        )
        self.description = self._field(
            record,
            "A sentence about it (you can leave this empty)",
            "Printed under the title, to tell the reader what the process is for.",
        )
        self.folder = self._field(
            record,
            "Where should it be kept?",
            "The recording, its screenshots and the finished document all go in this folder.",
            initial=DEFAULT_FOLDER,
            browse=self._pick_folder,
        )

        self.record_button = ttk.Button(
            record, text="Start recording", style="Go.TButton", command=self._record
        )
        self.record_button.pack(anchor="w", pady=(16, 6))
        ttk.Label(
            record,
            text=(
                "The screen dims and you drag a box around the warehouse app window. "
                "Then work through the process as you normally would: each tap raises a small "
                "question about what you just did. Press Ctrl+Shift+End when you are finished."
            ),
            style="Hint.TLabel", wraplength=560, justify="left",
        ).pack(anchor="w")

        # ----------------------------------------------------------- build
        build = ttk.LabelFrame(body, text="  Step 2  Make the document  ", padding=(14, 8, 14, 14))
        build.pack(fill="x", pady=(16, 0))

        self.recording_file = self._field(
            build,
            "Which recording?",
            "Filled in for you after a recording. Browse to pick an older one.",
            browse=self._pick_recording,
        )

        ttk.Label(build, text="What kind of document?", style="Field.TLabel").pack(
            anchor="w", pady=(12, 4)
        )
        self.style = tk.StringVar(value="task-guide")
        for value, title, explanation in (
            ("task-guide", "A task guide",
             "Numbered steps with a screenshot each, for training someone to do the process."),
            ("evidence", "Test evidence",
             "Each step paired with a screenshot of its result, to show a test was carried out."),
        ):
            ttk.Radiobutton(build, text=title, value=value, variable=self.style).pack(anchor="w")
            ttk.Label(build, text=f"     {explanation}", style="Hint.TLabel",
                      wraplength=540, justify="left").pack(anchor="w", pady=(0, 6))

        self.build_button = ttk.Button(
            build, text="Build document", style="Go.TButton", command=self._build
        )
        self.build_button.pack(anchor="w", pady=(10, 0))

        # ------------------------------------------------------- the rest
        tools = ttk.Frame(footer)
        tools.pack(fill="x", pady=(0, 6))
        ttk.Button(tools, text="Check this computer", command=self._check).pack(side="left")
        ttk.Button(tools, text="Open the folder", command=self._open_folder).pack(
            side="left", padx=(8, 0)
        )
        ttk.Label(tools, text="Anything the program is doing is reported below.",
                  style="Hint.TLabel").pack(side="left", padx=(12, 0))

        self.log = tk.Text(
            footer, height=7, wrap="word", state="disabled", relief="flat",
            background="#f4f4f4", foreground="#222", font=("Consolas" if os.name == "nt" else "monospace", 9),
        )
        self.log.pack(fill="both", expand=True)

        self._say("Ready. If this is a new computer, press 'Check this computer' first.")

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
            self._say(
                "Give the process a name first, in the box at the top. "
                "It becomes the title of the document."
            )
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


def borrow_parent_console() -> None:
    """Print into the terminal this was started from, if there was one.

    The program is built as a windowed one, so double-clicking it opens the
    launcher and never a console: nothing flashes, and there is no black window
    to close or to take the program down with it.

    The cost of that is having nowhere to print, which would leave the command
    line mute. So when it is started from a terminal it attaches to that
    terminal's console and prints there, the way a well-behaved Windows program
    does.

    Streams that already work are left alone. The launcher runs these same
    commands as child processes and hands them pipes; rebinding those to a
    console would send their output to a window instead of to the log pane.
    """
    if os.name != "nt" or not getattr(sys, "frozen", False):
        return
    if sys.stdout is not None and sys.stderr is not None:
        return  # already writing somewhere real, most likely a pipe

    try:
        import ctypes

        attach_parent = -1
        if not ctypes.windll.kernel32.AttachConsole(attach_parent):
            return  # started from Explorer: there is no terminal to print in

        if sys.stdout is None:
            sys.stdout = open("CONOUT$", "w", encoding="utf-8", buffering=1)  # noqa: SIM115
        if sys.stderr is None:
            sys.stderr = open("CONOUT$", "w", encoding="utf-8", buffering=1)  # noqa: SIM115
    except Exception:
        pass  # printing is a convenience; failing to do it must not stop the run


def main() -> None:
    """Open the launcher window."""
    Launcher().run()


if __name__ == "__main__":
    main()
