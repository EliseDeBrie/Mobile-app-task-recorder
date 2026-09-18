"""The recorder: watch the app, and write down what each action was.

D365 Task Recorder can name a step by itself because every control tells it what
was clicked and with what value. Nothing on a handheld does that, so this
recorder reads the screen instead: when a click or an Enter visibly changes it,
the region is photographed and OCR fills in the same fields a Task Recorder step
holds - the action, the control, the value, and the title and note annotations.

That reading is a guess, so nothing is final: the steps are corrected afterwards
in the review window, which is quicker than answering a popup per click and can
be done sitting down. `ask_each_step` brings the popup back for anyone who would
rather name each step as they take it.

The warehouse app is a window on the PC, not a page in a browser, so there is
no tab for an extension to photograph. Instead the recorder watches one region of
the screen - dragged out once at the start, the way Greenshot and PowerPoint's
screen clipping work - and grabs that region itself at each step. Watching only
the app also keeps the clock and the taskbar from triggering steps of their own.

Each step is captured twice: once at the action, and again over the couple of
seconds after it, keeping the frame that shows the result banner.

A small bar sits beside the region while recording, out of the picture, showing
the step count and the last step taken, with a button to stop.

Gestures, mirroring the Task Recorder pane:

* ``Ctrl+Shift+S`` start a subtask
* ``Ctrl+Shift+E`` end the current subtask
* ``Ctrl+Shift+I`` add an info step
* ``Ctrl+Shift+End`` stop and save
"""

import os
import time
import threading
from typing import Callable, Optional, Tuple

import numpy as np
import cv2

from .branding import apply_icon
from .dialogs import DialogHost, wait_for
from .frame_select import detect_toast
from .instructions import ACTION_CHOICES, ACTION_LABELS, ACTIONS, PREFERRED, render_instruction
from .recording import InfoStep, Recording, Step, SubtaskEnd, SubtaskStart
from .redaction import RedactionConfig
from .region import Region, open_capture, popup_position, virtual_screen
from .suggest import Suggestion, suggest_step
from .utils import ensure_dir, ensure_parent_dir, is_letter_key, mean_abs_diff, write_image

DEFAULT_ACTION_LABEL = ACTION_CHOICES[0][0]

#: How often the result capture samples the region, and for how long by default.
RESULT_SAMPLE_SEC = 0.12
RESULT_WINDOW_SEC = 2.5


def _ask_step(
    root,
    step_no: int,
    reason: str,
    diff: float,
    position: Optional[Tuple[int, int]] = None,
    suggestion: Optional[Suggestion] = None,
    screen: str = "",
) -> Optional[Step]:
    """Popup for one recorded action, previewing the sentence it will produce.

    Where OCR is available the screen, control and value arrive already filled
    in from the screenshot; the screen also carries over from the previous step,
    since a handheld process stays on one screen for several steps at a time.
    """
    import tkinter as tk
    from tkinter import ttk

    suggestion = suggestion or Suggestion()
    result = [None]
    row = [0]

    def next_row() -> int:
        row[0] += 1
        return row[0]

    win = tk.Toplevel(root)
    win.title(f"Step {step_no}")
    win.attributes("-topmost", True)
    win.resizable(False, False)
    if position is not None:
        win.geometry(f"+{int(position[0])}+{int(position[1])}")

    frm = ttk.Frame(win, padding=12)
    frm.grid()

    ttk.Label(frm, text=f"Step {step_no} ({reason}, diff={diff:.1f})").grid(
        row=next_row(), column=0, columnspan=2, sticky="w"
    )

    def field(label_text: str, initial: str = "") -> Tuple[tk.StringVar, ttk.Entry, ttk.Label]:
        label = ttk.Label(frm, text=label_text)
        label.grid(row=next_row(), column=0, columnspan=2, sticky="w", pady=(8, 0))
        var = tk.StringVar(value=initial)
        entry = ttk.Entry(frm, textvariable=var, width=45)
        entry.grid(row=next_row(), column=0, columnspan=2)
        return var, entry, label

    screen_var, _screen_entry, _screen_label = field(
        "Screen:", suggestion.screen or screen
    )

    ttk.Label(frm, text="Action:").grid(row=next_row(), column=0, sticky="w", pady=(8, 0))
    action_var = tk.StringVar(value=DEFAULT_ACTION_LABEL)
    ttk.Combobox(
        frm, textvariable=action_var, values=[label for label, _ in ACTION_CHOICES],
        state="readonly", width=42,
    ).grid(row=next_row(), column=0, columnspan=2, sticky="w")

    control_var, control_entry, control_label = field(
        "Button, field or page name:", suggestion.control
    )
    value_var, _value_entry, _value_label = field(
        "Value (for a scan or an entry):", suggestion.value
    )

    ttk.Label(frm, text="Step reads as:").grid(row=next_row(), column=0, sticky="w", pady=(8, 0))
    preview_var = tk.StringVar()
    ttk.Label(frm, textvariable=preview_var, width=45, wraplength=330, foreground="#1a5fb4").grid(
        row=next_row(), column=0, columnspan=2, sticky="w"
    )

    title_var, _title_entry, _title_label = field("Title (shown above the step):")

    ttk.Label(frm, text="Note (shown after the step):").grid(
        row=next_row(), column=0, sticky="w", pady=(8, 0)
    )
    note = tk.Text(frm, width=45, height=3)
    note.grid(row=next_row(), column=0, columnspan=2)

    loading_var = tk.BooleanVar(value=False)
    ttk.Checkbutton(frm, text="Loading / transition screen", variable=loading_var).grid(
        row=next_row(), column=0, columnspan=2, sticky="w", pady=(8, 0)
    )

    def refresh_preview(*_args) -> None:
        preview_var.set(
            render_instruction(
                ACTION_LABELS.get(action_var.get(), "tap"),
                control=control_var.get(),
                value=value_var.get(),
            )
        )

    for var in (action_var, control_var, value_var):
        var.trace_add("write", refresh_preview)
    refresh_preview()

    def on_ok():
        action = ACTION_LABELS.get(action_var.get(), "tap")
        control = control_var.get().strip()
        if not control and not ACTIONS[action].default_control:
            # Say why nothing happened, rather than ignoring the button.
            control_label.configure(
                text="Button, field or page name: needed for this action", foreground="#c01c28"
            )
            control_entry.focus_set()
            return
        result[0] = Step(
            action=action,
            control=control,
            value=value_var.get().strip(),
            screen=screen_var.get().strip(),
            title=title_var.get().strip(),
            note=note.get("1.0", "end").strip(),
            is_loading=loading_var.get(),
        )
        win.destroy()

    def on_skip():
        win.destroy()

    buttons = ttk.Frame(frm)
    buttons.grid(row=next_row(), column=0, columnspan=2, pady=(10, 0), sticky="e")
    ttk.Button(buttons, text="OK", command=on_ok).grid(row=0, column=0, padx=4)
    ttk.Button(buttons, text="Skip", command=on_skip).grid(row=0, column=1)
    win.bind("<Return>", lambda _e: on_ok())
    win.bind("<Escape>", lambda _e: on_skip())
    win.protocol("WM_DELETE_WINDOW", on_skip)

    # The popup opens over the app the user was just tapping, so it takes the
    # keyboard itself or the first characters are lost.
    win.focus_force()
    control_entry.focus_force()
    control_entry.selection_range(0, "end")

    wait_for(root, win)
    return result[0]


def _ask_text(root, window_title: str, prompt: str) -> Optional[str]:
    """Single-line prompt used by the subtask and info-step gestures."""
    import tkinter as tk
    from tkinter import ttk

    result = [None]

    win = tk.Toplevel(root)
    win.title(window_title)
    win.attributes("-topmost", True)
    win.resizable(False, False)

    frm = ttk.Frame(win, padding=12)
    frm.grid()
    ttk.Label(frm, text=prompt).grid(row=0, column=0, columnspan=2, sticky="w")

    text_var = tk.StringVar()
    entry = ttk.Entry(frm, textvariable=text_var, width=45)
    entry.grid(row=1, column=0, columnspan=2, pady=(6, 0))

    def on_ok():
        value = text_var.get().strip()
        if value:
            result[0] = value
        win.destroy()

    ttk.Button(frm, text="OK", command=on_ok).grid(row=2, column=0, pady=(10, 0))
    ttk.Button(frm, text="Cancel", command=win.destroy).grid(row=2, column=1, pady=(10, 0))
    win.bind("<Return>", lambda _e: on_ok())
    win.bind("<Escape>", lambda _e: win.destroy())
    win.protocol("WM_DELETE_WINDOW", win.destroy)

    win.focus_force()
    entry.focus_force()

    wait_for(root, win)
    return result[0]


class Session:
    """What the recorder bar shows, and what it asks the recorder to do."""

    def __init__(self):
        self.steps = 0
        self.last = "Nothing recorded yet."
        self.stop = threading.Event()


def _recorder_bar(root, session: Session, position, gestures):
    """A small strip that sits beside the app while recording.

    Recording used to be stopped with a key combination and nothing on screen
    said so, or said how many steps had been taken. This is that missing
    window: a count, a stop button, and the two gestures that are worth having
    to hand. It stays out of the captured region, so it never lands in a
    screenshot.
    """
    import tkinter as tk
    from tkinter import ttk

    win = tk.Toplevel(root)
    win.title("Recording")
    apply_icon(win)
    win.attributes("-topmost", True)
    win.resizable(False, False)
    if position is not None:
        win.geometry(f"+{int(position[0])}+{int(position[1])}")

    frame = ttk.Frame(win, padding=12)
    frame.grid()

    heading = ttk.Label(frame, text="Recording", font=("Segoe UI", 12, "bold"))
    heading.grid(row=0, column=0, columnspan=3, sticky="w")

    counter = tk.StringVar(value="0 steps")
    ttk.Label(frame, textvariable=counter, font=("Segoe UI", 22, "bold")).grid(
        row=1, column=0, columnspan=3, sticky="w", pady=(2, 0)
    )

    latest = tk.StringVar(value=session.last)
    ttk.Label(frame, textvariable=latest, wraplength=260, foreground="#444").grid(
        row=2, column=0, columnspan=3, sticky="w", pady=(0, 10)
    )

    ttk.Button(frame, text="Stop recording", command=session.stop.set).grid(
        row=3, column=0, columnspan=3, sticky="ew"
    )
    ttk.Button(frame, text="Start a section", command=gestures["subtask"]).grid(
        row=4, column=0, sticky="ew", pady=(8, 0)
    )
    ttk.Button(frame, text="Add a note", command=gestures["info"]).grid(
        row=4, column=2, sticky="ew", pady=(8, 0)
    )

    ttk.Label(
        frame,
        text="Work through the process as usual. Every step is written down; you can "
             "correct the wording afterwards.",
        wraplength=260, foreground="#666", font=("Segoe UI", 8),
    ).grid(row=5, column=0, columnspan=3, sticky="w", pady=(10, 0))

    def tick():
        counter.set(f"{session.steps} step" + ("" if session.steps == 1 else "s"))
        latest.set(session.last)
        if session.stop.is_set():
            win.destroy()
            return
        win.after(200, tick)

    win.protocol("WM_DELETE_WINDOW", session.stop.set)
    tick()
    return win


def _capture_result(
    grab: Callable[[], Optional[np.ndarray]],
    baseline,
    seconds: float,
    stop: threading.Event,
    sample_sec: float = RESULT_SAMPLE_SEC,
):
    """Watch the region after an action and keep the frame that shows the result.

    Only the best frame so far is held, so a long window costs no more memory
    than a short one. Without a banner, the last frame wins: it is the screen the
    action left behind.
    """
    best_frame = None
    best_score = 0.0
    best_family = ""
    last_frame = None

    deadline = time.time() + seconds
    while time.time() < deadline and not stop.is_set():
        frame = grab()
        if frame is None:
            break
        last_frame = frame

        toast = detect_toast(frame, baseline)
        if toast.found and toast.score > best_score:
            best_frame, best_score, best_family = frame, toast.score, toast.family

        time.sleep(sample_sec)

    if best_frame is not None:
        return best_frame, best_family
    return last_frame, ""


def _in_dialog(dialogs, build):
    """Open a dialog from wherever the caller happens to be.

    The bar's buttons are pressed on the thread that owns the windows, and a
    gesture arrives on a listener thread; `ask` runs the dialog at once for
    the first and queues it for the second.
    """
    return dialogs.ask(build)


def _guess_action(reason: str, suggestion: Suggestion) -> str:
    """Pick the likeliest action for a step nobody was asked about.

    A value counts only when Enter ended the action: a scan ends with Enter,
    and so does typing into a field. A click never enters a value, whatever
    text appeared under it - a menu opening shows plenty, and reading that as
    something the user typed produced steps like "enter 'Available actions'".
    On a handheld a value that ended with Enter is far more often scanned
    than typed, and either is one click to correct in the review window.
    """
    if reason == "enter" and suggestion.value:
        return "scan"
    return "tap"


def _signature(frame: np.ndarray) -> np.ndarray:
    """A small grey copy of a frame, cheap to compare with the next one."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return cv2.resize(gray, (160, 90), interpolation=cv2.INTER_AREA)


class StepTracker:
    """Turns taps into steps, one at a time, without making the next tap wait.

    Each step is captured twice: the action frame at the tap, and the result
    over the seconds after it. The result watch used to hold the recorder until
    the window ran out, which was harmless while a popup held the user too, and
    is not now that nothing does: at a tap a second, with no banner to cut the
    watch short, two taps in three were thrown away while the recorder waited.

    So the watch runs alongside, and the next tap ends it. The screen the user
    tapped on next is the result there was, and the recorder is free to write
    the new tap down the moment it happens.

    Everything that touches the screen, the OCR engine or a window is handed in,
    which is what lets this be exercised with a list of frames and a clock.
    """

    def __init__(
        self,
        recording: Recording,
        *,
        grab: Callable[[], np.ndarray],
        watch: Callable[[np.ndarray, threading.Event, dict], None],
        suggest: Optional[Callable[[np.ndarray, Optional[Tuple[int, int]], np.ndarray], Suggestion]],
        ask: Optional[Callable[[int, str, float, Suggestion, str], Optional[Step]]],
        save_shot: Callable[[Optional[np.ndarray], str], str],
        persist: Callable[[], None],
        announce: Callable[[Step], None],
        diff_threshold: float,
        min_gap_sec: float,
        result_window: float,
        capture_screenshots: bool = True,
    ):
        self.recording = recording
        self.grab = grab
        self.watch = watch
        self.suggest = suggest
        self.ask = ask
        self.save_shot = save_shot
        self.persist = persist
        self.announce = announce
        self.diff_threshold = diff_threshold
        self.min_gap_sec = min_gap_sec
        self.result_window = result_window
        self.capture_screenshots = capture_screenshots

        self._lock = threading.Lock()
        self._busy = False
        self._pending = None  # the last step, whose result is still being watched

        self.last_frame = grab()
        self.last_sig = _signature(self.last_frame)
        self.last_screen = ""
        self.last_mark_t = 0.0

    # ------------------------------------------------------------- the claim

    @property
    def busy(self) -> bool:
        return self._busy

    def claim(self) -> bool:
        """Take the recorder for one step or one dialog; False if it is taken."""
        with self._lock:
            if self._busy:
                return False
            self._busy = True
            return True

    def release(self) -> None:
        with self._lock:
            self._busy = False

    # -------------------------------------------------------------- one tap

    def notice_tap(self) -> None:
        """A tap has just happened: end the previous step's result watch now.

        The watch has to stop at the tap itself, not when the tap is looked at
        a moment later. By then the screen has changed, and the last frame the
        watch saw would be the new screen - which, used as the baseline, makes
        the new tap look like it changed nothing.
        """
        pending = self._pending
        if pending is not None:
            pending[3].set()

    def consider(self, reason: str, click: Optional[Tuple[int, int]], now: float) -> Optional[Step]:
        """Decide whether the tap just taken is a step, and write it if so."""
        if now - self.last_mark_t < self.min_gap_sec:
            return None
        if not self.claim():
            return None

        try:
            # The previous step's result watch was stopped at the tap; its
            # last frame is the screen the tap was taken on, which is that
            # step's result and the baseline for this one.
            self._settle()
            before = self.last_frame

            frame = self.grab()
            signature = _signature(frame)
            diff = mean_abs_diff(signature, self.last_sig)
            if diff < self.diff_threshold:
                self.last_frame, self.last_sig = frame, signature
                return None

            step_no = len(self.recording.steps) + 1
            stop = threading.Event()
            holder: dict = {}
            watcher = None
            if self.capture_screenshots:
                watcher = threading.Thread(
                    target=self.watch, args=(before, stop, holder), daemon=True
                )
                watcher.start()

            suggestion = Suggestion()
            if self.suggest is not None and self.capture_screenshots:
                suggestion = self.suggest(frame, click, before)

            if self.ask is not None:
                step = self.ask(step_no, reason, diff, suggestion, self.last_screen)
            else:
                # Written down as read off the screen. Interrupting someone
                # for every tap makes a short process a long one, and the
                # wording is easier to fix afterwards, with the screenshots
                # to look at.
                action = _guess_action(reason, suggestion)
                step = Step(
                    action=action,
                    control=suggestion.control,
                    # A tap has no value, whatever text the screen showed.
                    value=suggestion.value if ACTIONS[action].takes_value else "",
                    screen=suggestion.screen or self.last_screen,
                )

            if step is None:
                stop.set()
                if watcher is not None:
                    watcher.join(timeout=self.result_window + 1.0)
                self.last_frame, self.last_sig = frame, signature
                return None

            step.t = round(now, 3)
            step.reason = reason
            step.diff = round(diff, 2)
            if self.capture_screenshots:
                step.action_img = self.save_shot(frame, f"step_{step_no:02d}_action.png")

            self.last_screen = step.screen or self.last_screen
            self.last_mark_t = now
            self.last_frame, self.last_sig = frame, signature
            self.recording.add(step)
            if watcher is not None:
                self._pending = (step, step_no, watcher, stop, holder)
            self.persist()
            self.announce(step)
            return step
        finally:
            self.release()

    # ---------------------------------------------------------- the result

    def _settle(self, let_it_finish: bool = False) -> None:
        """Close the pending step's result watch and write what it found."""
        pending, self._pending = self._pending, None
        if pending is None:
            return

        step, step_no, watcher, stop, holder = pending
        if not let_it_finish:
            stop.set()
        watcher.join(timeout=self.result_window + 1.0)

        step.result_img = self.save_shot(holder.get("frame"), f"step_{step_no:02d}_result.png")
        step.result_toast = holder.get("toast", "")

        # The last frame the watch saw is the screen the step left behind: the
        # baseline the next step is judged against.
        settled = holder.get("last")
        if settled is not None:
            self.last_frame, self.last_sig = settled, _signature(settled)
        self.persist()

    def finish(self) -> None:
        """Let the last step's result watch run its course, then write it."""
        self._settle(let_it_finish=True)


def run_marker_recorder(
    out_path: str,
    monitor_index: int = 1,
    min_gap_sec: float = 0.75,
    post_delay_sec: float = 0.30,
    diff_threshold: float = 7.5,
    name: str = "",
    description: str = "",
    region: Optional[Region] = None,
    region_spec: str = "",
    capture_screenshots: bool = True,
    suggest: bool = True,
    ask_each_step: bool = False,
    result_window: float = RESULT_WINDOW_SEC,
    redaction: Optional[RedactionConfig] = None,
):
    """Record a task recording for a handheld process."""
    from pynput import keyboard, mouse

    from .region import select_region, use_physical_pixels

    ensure_parent_dir(out_path)

    # Before any window: the box dragged over the app has to mean the same
    # pixels to Tk as it does to the screen capture.
    use_physical_pixels()

    # The windows live on this thread. Tk tears its interpreter down from
    # whichever thread drops the last reference, and aborts the process if
    # that is not the thread that made it; keeping the root here, where the
    # process ends, is what stops every Stop from being a crash.
    dialogs = DialogHost().open()

    if region is None and (region_spec or "").strip().lower() == "select":
        region = dialogs.ask(select_region)
        if region is None:
            dialogs.close()
            raise RuntimeError("No region selected.")

    recording = Recording(
        name=name or "Untitled recording",
        description=description,
        start_epoch=time.time(),
        monitor_index=monitor_index,
        diff_threshold=diff_threshold,
        region=region,
    )
    recording.source_path = out_path

    shots_dir = ""
    shots_name = ""
    if capture_screenshots:
        shots_name = f"{os.path.splitext(os.path.basename(out_path))[0]}_screenshots"
        shots_dir = os.path.join(os.path.dirname(os.path.abspath(out_path)), shots_name)
        ensure_dir(shots_dir)

    session = Session()
    last_click: Optional[Tuple[int, int]] = None
    pressed = set()
    pending_timer: Optional[threading.Timer] = None
    lock = threading.Lock()

    # A capture session belongs to the thread that made it, so each thread gets
    # its own. Steps are detected on timer threads and the result is watched on
    # another, and sharing one session across them returns torn or blank frames.
    captures = threading.local()

    def capture_session():
        capture = getattr(captures, "session", None)
        if capture is None:
            capture = open_capture()
            captures.session = capture
        return capture

    with open_capture() as probe:
        monitors = probe.monitors
        monitor = (
            region.to_monitor() if region is not None
            else (monitors[monitor_index] if monitor_index else monitors[0])
        )

    screen = virtual_screen()
    popup_at = popup_position(region, screen)

    def grab_frame():
        return np.array(capture_session().grab(monitor))[:, :, :3]

    def save_shot(frame, filename: str) -> str:
        if frame is None or not shots_dir:
            return ""
        if redaction is not None:
            frame = redaction.apply(frame)
        write_image(os.path.join(shots_dir, filename), frame)
        return f"{shots_name}/{filename}"

    def elapsed() -> float:
        return time.time() - recording.start_epoch

    def save_recording(announce: bool = True):
        """Write the recording out. Called after every step, not only at the end,
        so a crash or a lost session costs the current step at most."""
        try:
            recording.save(out_path)
        except OSError as exc:
            print(f"Could not save the recording: {exc}")
            return
        if announce:
            print(f"Saved {len(recording.steps)} step(s) to: {out_path}")

    def region_point(click: Optional[Tuple[int, int]]) -> Optional[Tuple[int, int]]:
        """Put a screen click into the captured region's own coordinates."""
        if click is None:
            return None
        x, y = click
        point = (x - monitor["left"], y - monitor["top"])
        if 0 <= point[0] < monitor["width"] and 0 <= point[1] < monitor["height"]:
            return point
        return None

    def watch_result(baseline, stop: threading.Event, holder: dict) -> None:
        """Watch the region for the result, on a capture session of its own."""
        with open_capture() as thread_session:
            def grab():
                frame = np.array(thread_session.grab(monitor))[:, :, :3]
                holder["last"] = frame
                return frame

            holder["frame"], holder["toast"] = _capture_result(
                grab, baseline, result_window, stop
            )

    def read_screen(frame, click, before) -> Suggestion:
        return suggest_step(frame, point=region_point(click), before=before)

    def ask_about(step_no, reason, diff, suggestion, last_screen) -> Optional[Step]:
        return dialogs.ask(
            lambda root: _ask_step(root, step_no, reason, diff, popup_at, suggestion, last_screen)
        )

    def announce(step: Step) -> None:
        session.steps = len(recording.steps)
        session.last = step.instruction(PREFERRED)
        print(f"Step {session.steps}: {session.last}")

    tracker = StepTracker(
        recording,
        grab=grab_frame,
        watch=watch_result,
        suggest=read_screen if suggest else None,
        ask=ask_about if ask_each_step else None,
        save_shot=save_shot,
        persist=lambda: save_recording(announce=False),
        announce=announce,
        diff_threshold=diff_threshold,
        min_gap_sec=min_gap_sec,
        result_window=result_window,
        capture_screenshots=capture_screenshots,
    )

    def maybe_mark(reason: str):
        nonlocal pending_timer
        with lock:
            pending_timer = None
        # A click is only a step where the tap landed: a click on the launcher
        # or the bar says nothing about the app.
        click = last_click if reason == "mouse_click" else None
        tracker.consider(reason, click, elapsed())

    def schedule_check(reason: str):
        nonlocal pending_timer
        tracker.notice_tap()
        with lock:
            if pending_timer is not None:
                return
            pending_timer = threading.Timer(post_delay_sec, maybe_mark, args=(reason,))
            pending_timer.start()

    def start_subtask():
        if not tracker.claim():
            print("Finish the open step first, then start the subtask.")
            return
        try:
            subtask_name = _in_dialog(
                dialogs, lambda root: _ask_text(root, "Name this section", "What is this part called?")
            )
        finally:
            tracker.release()
        if subtask_name:
            recording.add(SubtaskStart(t=round(elapsed(), 3), name=subtask_name))
            save_recording(announce=False)
            print(f"Subtask started: {subtask_name}")

    def end_subtask():
        if recording.open_subtasks() == 0:
            print("No subtask is open.")
            return
        recording.add(SubtaskEnd(t=round(elapsed(), 3)))
        save_recording(announce=False)
        print("Subtask ended.")

    def add_info_step():
        if not tracker.claim():
            print("Finish the open step first, then add the info step.")
            return
        try:
            text = _in_dialog(
                dialogs, lambda root: _ask_text(root, "Add a note", "What should the reader know?")
            )
        finally:
            tracker.release()
        if text:
            recording.add(InfoStep(t=round(elapsed(), 3), text=text))
            save_recording(announce=False)
            print(f"Info step: {text}")

    def on_click(x, y, button, is_pressed):
        nonlocal last_click
        if is_pressed:
            last_click = (int(x), int(y))
            schedule_check("mouse_click")

    def on_key_press(key):
        pressed.add(key)

        ctrl = keyboard.Key.ctrl_l in pressed or keyboard.Key.ctrl_r in pressed
        shift = keyboard.Key.shift_l in pressed or keyboard.Key.shift_r in pressed

        # pynput stops the listener when a handler returns False; None carries on.
        if ctrl and shift:
            if key == keyboard.Key.end:
                print("Stopping.")
                return False
            if is_letter_key(key, "s"):
                threading.Thread(target=start_subtask, daemon=True).start()
                return None
            if is_letter_key(key, "e"):
                end_subtask()
                return None
            if is_letter_key(key, "i"):
                threading.Thread(target=add_info_step, daemon=True).start()
                return None

        if key == keyboard.Key.enter:
            schedule_check("enter")
        return None

    def on_key_release(key):
        if key in pressed:
            pressed.remove(key)

    print(f"Recording '{recording.name}'.")
    if region is not None:
        print(f"Watching {region.describe()}.")
    else:
        print(f"Watching the whole of monitor {monitor_index}.")
    if capture_screenshots:
        print(f"Screenshots go to: {shots_dir}")
        if suggest:
            from . import ocr as ocr_module

            if ocr_module.available():
                print("Reading the screen to write each step down for you.")
            else:
                print(
                    "No OCR engine, so the steps are written down without their wording. "
                    "Run 'whs-recorder check' to see why."
                )
        if redaction is not None and not redaction.is_empty():
            print(f"Redaction active while recording: {redaction.describe()}")
    else:
        print("Screenshots are off: build the document from a screen recording instead.")
    if ask_each_step:
        print("Every action raises a popup to fill in.")
    else:
        print("Nothing to answer while you work: correct the wording afterwards with "
              "'whs-recorder review'.")
    print("Ctrl+Shift+S subtask, Ctrl+Shift+E end subtask, Ctrl+Shift+I info step, Ctrl+Shift+End stop.")

    m_listener = mouse.Listener(on_click=on_click)
    k_listener = keyboard.Listener(on_press=on_key_press, on_release=on_key_release)

    bar_at = popup_position(region, screen, popup_size=(300, 260))
    dialogs.ask(
        lambda root: _recorder_bar(
            root, session, bar_at,
            {"subtask": start_subtask, "info": add_info_step},
        )
    )
    # Where it went is worth saying. The bar is placed beside the region being
    # captured, which on a second monitor is nowhere near where someone is
    # looking, and "I cannot see it" is otherwise impossible to answer.
    print(f"The recording bar is open at {bar_at[0]},{bar_at[1]}. "
          f"Press 'Stop recording' on it when you are done.")

    m_listener.start()
    k_listener.start()
    try:
        # Either the button on the bar or the key combination ends the session.
        # The wait is the window loop itself, which is what runs the popups
        # the timer threads ask for.
        dialogs.serve(until=lambda: session.stop.is_set() or not k_listener.running)
    except KeyboardInterrupt:
        pass
    finally:
        session.stop.set()
        k_listener.stop()
        m_listener.stop()
        with lock:
            if pending_timer is not None:
                pending_timer.cancel()
                pending_timer = None

        # A popup may still be open, or a step may be mid-capture. Wait for it,
        # so stopping never costs the step that was being filled in; then let
        # the last step's result watch run out, so its banner is not lost to
        # the stop button being pressed straight after it.
        deadline = time.time() + result_window + 30.0
        while tracker.busy and time.time() < deadline:
            time.sleep(0.1)
        tracker.finish()

        save_recording()
        dialogs.close()

    return recording
