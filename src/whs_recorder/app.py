"""The window you get when you double-click the program.

Everything this tool does is available from the command line, but a consultant
on a customer's machine should not have to open a terminal to record a process.
This is that window: name the recording, press a button, work through the
process on the handheld, press stop, and the Word document is there.

The document is the point. It is made the moment a recording stops, made again
whenever corrections are saved, and opened when the review window is closed,
so nobody has to find a Build button to get what they came for. The recording
itself - the JSON beside it - is what the document is made from, and is what
'Check the steps' reopens.

Recording runs as a separate process rather than inside this one. Tk keeps a
per-thread interpreter, the recorder opens windows of its own on its own
thread, and two interpreters in one process is the hazard that makes a dialog
render but never answer. A separate process sidesteps it entirely, and a crash
while recording leaves this window standing.
"""

import collections
import contextlib
import os
import queue
import subprocess
import sys
import threading
from typing import Any, List, Optional

from . import __version__
from .branding import apply_icon
from .dialogs import collect_windows

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


def document_for(recording_path: str) -> str:
    """The document a recording turns into: the same name, beside it."""
    return os.path.splitext(recording_path)[0] + ".docx"


def build_folder_for(recording_path: str) -> str:
    """Where a recording's builds go: each build in a run folder of its own,
    with its pictures and manifest, so no build overwrites another."""
    return os.path.splitext(recording_path)[0] + "_build"


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
        #: Work for the window's own thread, handed over from the worker: Tk
        #: may only be driven from the thread that owns it.
        self.calls: "queue.Queue[Any]" = queue.Queue()
        #: The command running now, if any: its process and what to do when
        #: it ends. Whether one is running or about to, and the ones waiting
        #: their turn. Two builds writing the same document at once would
        #: corrupt it, so commands run one after another.
        self.job: Optional[dict] = None
        self.active = False
        self.waiting = collections.deque()
        self.reviewing = None

        self.root = tk.Tk()
        self.root.title(WINDOW_TITLE)
        apply_icon(self.root)
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
                "Then simply work through the process: every step is written down as you go, "
                "with nothing to answer. A small bar shows the step count and has a stop "
                "button on it (Ctrl+Shift+End stops it too). When you stop, the Word document "
                "is made straight away, and the steps open in a window where you can correct "
                "the wording; press Done there and the document opens."
            ),
            style="Hint.TLabel", wraplength=560, justify="left",
        ).pack(anchor="w")

        # ----------------------------------------------------------- build
        build = ttk.LabelFrame(body, text="  Step 2  Make the document  ", padding=(14, 8, 14, 14))
        build.pack(fill="x", pady=(16, 0))

        self.recording_file = self._field(
            build,
            "Which recording?",
            "Filled in for you after a recording. Browse to pick an older one: the recording "
            "is the .json file.",
            browse=self._pick_recording,
        )
        self.document_file = self._field(
            build,
            "Save the document as",
            "Filled in for you: the process name, in the folder above. Browse to put it "
            "somewhere else or call it something else - a customer's project folder, say. "
            "It is replaced each time the document is made.",
            browse=self._pick_document,
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

        buttons = ttk.Frame(build)
        buttons.pack(anchor="w", pady=(10, 0))
        self.review_button = ttk.Button(
            buttons, text="Check the steps", command=self._review_chosen
        )
        self.review_button.pack(side="left", padx=(0, 10))
        self.build_button = ttk.Button(
            buttons, text="Build document", style="Go.TButton", command=self._build
        )
        self.build_button.pack(side="left")
        ttk.Label(
            build,
            text="'Check the steps' opens the list of recorded steps so you can correct the "
                 "wording or leave a step out; the document is remade when you save. "
                 "'Build document' makes it again from the recording as it is, and opens it.",
            style="Hint.TLabel", wraplength=560, justify="left",
        ).pack(anchor="w", pady=(8, 0))

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
        """Move output from the worker thread into the log, and act on what
        the worker reported - on this thread, the one that owns the window."""
        try:
            while True:
                self._say(self.messages.get_nowait())
        except queue.Empty:
            pass
        try:
            while True:
                item = self.calls.get_nowait()
                if callable(item):
                    item()
                else:
                    job, exit_code = item
                    self._finished(job, exit_code)
        except queue.Empty:
            pass
        self.root.after(100, self._drain)

    @property
    def running(self) -> Optional[subprocess.Popen]:
        return self.job.get("process") if self.job else None

    def _busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self.record_button.configure(state=state)
        self.build_button.configure(state=state)
        self.review_button.configure(state=state)

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
            self.document_file.set(document_for(chosen))

    def _pick_document(self) -> None:
        from tkinter import filedialog

        current = self.document_file.get().strip() or document_for(
            self.recording_file.get() or self.recording_path()
        )
        chosen = filedialog.asksaveasfilename(
            initialdir=os.path.dirname(current) or self.folder.get(),
            initialfile=os.path.basename(current),
            defaultextension=".docx",
            filetypes=[("Word document", "*.docx")],
        )
        if chosen:
            self.document_file.set(chosen)

    def document_path(self, recording_path: str) -> str:
        """Where the document goes: where the person said, else beside the recording."""
        chosen = self.document_file.get().strip()
        if not chosen:
            return document_for(recording_path)
        if not chosen.lower().endswith(".docx"):
            chosen += ".docx"
        return chosen

    def _open_folder(self) -> None:
        folder = self.folder.get()
        if not os.path.isdir(folder):
            self._say(f"Nothing there yet: {folder}")
            return
        self._open_path(folder)

    # ------------------------------------------------------------------ actions

    def _run(self, args: List[str], done: str, on_success=None, on_finish=None) -> None:
        """Run the tool as a command and stream its output into the log.

        `on_success` runs on the window's own thread once the command has
        finished cleanly; `on_finish` runs however it ended, with the exit
        code, for the caller that can judge for itself whether the outcome is
        usable. Both run on the window's thread: a Tk window may only be
        driven from the thread that owns it.

        One command at a time: a second request waits for the first to finish.

        The worker thread is handed the queues and a job record, and never the
        window. A thread that holds the window can end up the last to let go
        of it, and Tk aborts the whole process when a window is finalised on
        a thread other than the one that made it - which is how the recorder
        used to crash on every Stop.
        """
        if self.active:
            self.waiting.append((args, done, on_success, on_finish))
            return
        self.active = True
        self._busy(True)

        job = {"on_success": on_success, "on_finish": on_finish, "process": None}
        self.job = job
        messages, calls = self.messages, self.calls
        command = command_prefix() + args
        environment = command_environment()

        def worker():
            exit_code = -1
            try:
                process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    env=environment,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                job["process"] = process
                for line in process.stdout:
                    messages.put(line)
                process.wait()
                exit_code = process.returncode
                messages.put(done if exit_code == 0 else "Stopped with an error.")
            except Exception as exc:
                messages.put(f"Could not run it: {exc}")
            finally:
                job["process"] = None
                calls.put((job, exit_code))

        threading.Thread(target=worker, daemon=True).start()

    def _finished(self, job: dict, exit_code: int) -> None:
        """A command is over: free the buttons, act on how it ended, and
        start the next one waiting."""
        if job is self.job:
            self.job = None
        self.active = False
        self._busy(False)
        # Any window closed since the last command - the review, a file
        # dialog - is freed here, on the window thread, before the next worker
        # thread can be the one to free it and take the process down.
        collect_windows()
        if exit_code == 0 and job["on_success"] is not None:
            job["on_success"]()
        if job["on_finish"] is not None:
            job["on_finish"](exit_code)
        if self.waiting and not self.active:
            self._run(*self.waiting.popleft())

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
        if not self.document_file.get().strip():
            self.document_file.set(document_for(path))

        self._say(f"\nRecording to {path}")
        self._say("Drag a box around the warehouse app. Press 'Stop recording' when you are done.")
        self._run(
            ["mark", "--out", path, "--name", self.name.get(), "--description", self.description.get()],
            "Recording saved.",
            on_finish=lambda code: self._after_recording(path, code),
        )

    def _after_recording(self, path: str, exit_code: int = 0) -> None:
        """The recording is in: make the document, and open the steps to check.

        The document comes first and without being asked for, so that there
        is one even if the review window is closed straight away. Saving
        corrections makes it again.

        The recorder saves the recording before it does anything else on the
        way out, so an error at that point is not a reason to leave the
        recording sitting there unbuilt: if the file is there, carry on, and
        say what happened.
        """
        if not os.path.isfile(path):
            self._say("No recording was saved, so there is nothing to build.")
            return
        if exit_code != 0:
            self._say(
                "The recorder reported an error on the way out, but the recording was "
                "saved. Carrying on with it."
            )
        self._build_document(path)
        self._review(path)

    def _review_chosen(self) -> None:
        """Open the review window for whichever recording is filled in."""
        path = self.recording_file.get() or self.recording_path()
        if not os.path.isfile(path):
            self._say(f"No recording at {path}. Record one first, or browse to it.")
            return
        self._review(path)

    def _review(self, path: str) -> None:
        """Show the recorded steps, with building the document one press away.

        The window is a child of this one rather than a separate process: it
        only reads and writes the recording file, and a second Tk window on the
        same thread is exactly what Tk is happy with.
        """
        from .review import Review

        self.recording_file.set(path)

        # One window per recording. A second one over the same file would hold
        # its own copy of the steps, and whichever was saved last would quietly
        # throw the other's corrections away.
        if self._review_open():
            self.reviewing.root.deiconify()
            self.reviewing.root.lift()
            self._say("The steps are already open.")
            return

        try:
            self.reviewing = Review(
                path,
                on_saved=self._steps_saved,
                on_closed=self._steps_done,
            )
        except Exception as exc:
            self.reviewing = None
            self._say(f"Could not open the steps: {exc}")
            return

        self._say(
            f"Checking the steps in {os.path.basename(path)}. Save remakes the document; "
            f"Done makes it and opens it."
        )
        self.reviewing.run()

    def _steps_saved(self, path: str) -> None:
        self._say("Steps saved. Updating the document...")
        self._build_document(path)

    def _steps_done(self, path: str) -> None:
        self._build_document(path, then_open=True)

    def _review_open(self) -> bool:
        """Whether a review window from earlier is still on screen."""
        if self.reviewing is None:
            return False
        try:
            return bool(self.reviewing.root.winfo_exists())
        except Exception:
            return False  # already gone, along with the widget that could say so

    def _build(self) -> None:
        """The button: build the chosen recording's document and open it."""
        path = self.recording_file.get() or self.recording_path()
        if not os.path.isfile(path):
            self._say(f"No recording at {path}. Record one first, or browse to it.")
            return
        self._build_document(path, then_open=True)

    def _build_document(self, path: str, then_open: bool = False) -> None:
        """Make the document for a recording, where the person asked for it."""
        document = self.document_path(path)
        self._say(f"\nMaking the document from {os.path.basename(path)}...")
        self._run(
            [
                "build", "--markers", path,
                "--out", build_folder_for(path),
                "--document", document,
                "--style", self.style.get(),
                "--skip-loading",
            ],
            f"Document ready: {document}",
            on_success=(lambda: self._open_path(document)) if then_open else None,
        )

    def _open_path(self, path: str) -> None:
        """Open a file or folder with whatever Windows would open it with."""
        if not os.path.exists(path):
            self._say(f"Nothing at {path}.")
            return
        try:
            if os.name == "nt":
                os.startfile(path)  # noqa: S606 - the point is to open it
            else:
                subprocess.Popen(["xdg-open", path])
        except OSError as exc:
            self._say(f"Could not open {path}: {exc}")

    def run(self) -> None:
        self.root.mainloop()
        # The window is closing: free it here, while a build may still be
        # running on a worker thread that must not be the one to do it.
        with contextlib.suppress(Exception):
            self.root.destroy()
        collect_windows()


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


def print_as_it_happens() -> None:
    """Send each printed line on at once, rather than when the buffer fills.

    The launcher reads the recorder's output through a pipe, and Python
    buffers a pipe in blocks of several kilobytes: "Step 3: ..." and "The
    recording bar is open at ..." would all land in the log pane together
    when recording ended, which is the opposite of a log. A terminal is line
    buffered already, so this changes nothing there.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(line_buffering=True)
        except (AttributeError, ValueError):
            pass  # not a text stream that can be reconfigured; nothing lost


def main() -> None:
    """Open the launcher window."""
    Launcher().run()


if __name__ == "__main__":
    main()
