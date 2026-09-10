"""The recorder: watch the app, and ask what each action was.

D365 Task Recorder can name a step by itself because every control tells it what
was clicked and with what value. Nothing on a handheld does that, so this
recorder asks. When a click or an Enter visibly changes the screen it raises a
popup carrying the same fields a Task Recorder step holds - the action, the
control, the value, and the title and note annotations - and shows the sentence
those fields will produce in the guide.

The warehouse app is a window on the PC, not a page in a browser, so there is
no tab for an extension to photograph. Instead the recorder watches one region of
the screen - dragged out once at the start, the way Greenshot and PowerPoint's
screen clipping work - and grabs that region itself at each step. Watching only
the app also keeps the clock and the taskbar from triggering steps of their own.

Each step is captured twice: once at the action, and again over the couple of
seconds after it, keeping the frame that shows the result banner. That second
capture runs while the popup is open, and the popup is placed beside the region
so it never ends up in the picture.

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

from .dialogs import DialogHost, wait_for
from .frame_select import detect_toast
from .instructions import ACTION_CHOICES, ACTION_LABELS, ACTIONS, PREFERRED, render_instruction
from .recording import InfoStep, Recording, Step, SubtaskEnd, SubtaskStart
from .redaction import RedactionConfig
from .region import Region, open_capture, popup_position, virtual_screen
from .suggest import Suggestion, suggest_step
from .utils import ensure_dir, ensure_parent_dir, is_letter_key, mean_abs_diff

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
    result_window: float = RESULT_WINDOW_SEC,
    redaction: Optional[RedactionConfig] = None,
):
    """Record a task recording for a handheld process."""
    from pynput import keyboard, mouse

    from .region import select_region

    ensure_parent_dir(out_path)

    dialogs = DialogHost().start()

    if region is None and (region_spec or "").strip().lower() == "select":
        region = dialogs.ask(select_region)
        if region is None:
            dialogs.stop()
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

    last_mark_t = 0.0
    last_click: Optional[Tuple[int, int]] = None
    last_screen = ""
    pressed = set()
    pending_timer: Optional[threading.Timer] = None
    dialog_open = False
    lock = threading.Lock()

    sct = open_capture()
    if region is not None:
        monitor = region.to_monitor()
    else:
        monitor = sct.monitors[monitor_index] if monitor_index else sct.monitors[0]

    screen = virtual_screen()
    popup_at = popup_position(region, screen)

    def grab_frame():
        return np.array(sct.grab(monitor))[:, :, :3]

    def grab_signature(frame=None):
        gray = cv2.cvtColor(grab_frame() if frame is None else frame, cv2.COLOR_BGR2GRAY)
        return cv2.resize(gray, (160, 90), interpolation=cv2.INTER_AREA)

    def save_shot(frame, filename: str) -> str:
        if frame is None or not shots_dir:
            return ""
        if redaction is not None:
            frame = redaction.apply(frame)
        cv2.imwrite(os.path.join(shots_dir, filename), frame)
        return f"{shots_name}/{filename}"

    last_frame = grab_frame()
    last_sig = grab_signature(last_frame)

    def elapsed() -> float:
        return time.time() - recording.start_epoch

    def claim_dialog() -> bool:
        nonlocal dialog_open
        with lock:
            if dialog_open:
                return False
            dialog_open = True
            return True

    def release_dialog() -> None:
        nonlocal dialog_open
        with lock:
            dialog_open = False

    def save_recording():
        recording.save(out_path)
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

    def maybe_mark(reason: str):
        nonlocal last_mark_t, last_sig, last_frame, last_screen, pending_timer

        with lock:
            pending_timer = None
            if dialog_open:
                return

        t_now = elapsed()
        if t_now - last_mark_t < min_gap_sec:
            return

        # The screen before the action is the baseline a result banner is
        # judged against: by the time the action is captured the banner may
        # already be up, and comparing it with itself would hide it.
        before_frame = last_frame

        new_frame = grab_frame()
        new_sig = grab_signature(new_frame)
        diff = mean_abs_diff(new_sig, last_sig)
        if diff < diff_threshold:
            last_frame = new_frame
            last_sig = new_sig
            return

        if not claim_dialog():
            return

        # Capture before the popup opens, and keep watching for the result
        # banner while the popup is being filled in.
        step_no = len(recording.steps) + 1
        action_frame = new_frame if capture_screenshots else None
        stop_result = threading.Event()
        result_holder = {}

        def watch_result():
            # Its own capture session: one is not safe to share across threads.
            with open_capture() as thread_sct:
                result_holder["frame"], result_holder["toast"] = _capture_result(
                    lambda: np.array(thread_sct.grab(monitor))[:, :, :3],
                    before_frame,
                    result_window,
                    stop_result,
                )

        watcher = None
        if capture_screenshots:
            watcher = threading.Thread(target=watch_result, daemon=True)
            watcher.start()

        # The claim is held until the step is written, so stopping the recorder
        # mid-step waits for it rather than saving without it.
        # Read the screen so the popup arrives filled in, where OCR is available.
        suggestion = Suggestion()
        point = region_point(last_click) if reason == "mouse_click" else None
        if suggest and action_frame is not None:
            suggestion = suggest_step(action_frame, point=point, before=before_frame)

        try:
            step = dialogs.ask(
                lambda root: _ask_step(
                    root, step_no, reason, diff, popup_at, suggestion, last_screen
                )
            )

            if step is None:
                stop_result.set()
                if watcher is not None:
                    watcher.join(timeout=result_window + 1.0)
                last_frame = new_frame
                last_sig = new_sig
                return

            step.t = round(t_now, 3)
            step.reason = reason
            step.diff = round(diff, 2)

            if watcher is not None:
                watcher.join(timeout=result_window + 1.0)
                step.action_img = save_shot(action_frame, f"step_{step_no:02d}_action.png")
                step.result_img = save_shot(result_holder.get("frame"), f"step_{step_no:02d}_result.png")
                step.result_toast = result_holder.get("toast", "")

            last_screen = step.screen or last_screen
            last_mark_t = t_now
            last_frame = grab_frame()
            last_sig = grab_signature(last_frame)
            recording.add(step)
            print(f"Step {len(recording.steps)}: {step.instruction(PREFERRED)}")
        finally:
            release_dialog()

    def schedule_check(reason: str):
        nonlocal pending_timer
        with lock:
            if pending_timer is not None or dialog_open:
                return
            pending_timer = threading.Timer(post_delay_sec, maybe_mark, args=(reason,))
            pending_timer.start()

    def start_subtask():
        if not claim_dialog():
            return
        try:
            subtask_name = dialogs.ask(
                lambda root: _ask_text(root, "Start subtask", "Name of the subtask:")
            )
        finally:
            release_dialog()
        if subtask_name:
            recording.add(SubtaskStart(t=round(elapsed(), 3), name=subtask_name))
            print(f"Subtask started: {subtask_name}")

    def end_subtask():
        if recording.open_subtasks() == 0:
            print("No subtask is open.")
            return
        recording.add(SubtaskEnd(t=round(elapsed(), 3)))
        print("Subtask ended.")

    def add_info_step():
        if not claim_dialog():
            return
        try:
            text = dialogs.ask(
                lambda root: _ask_text(root, "Info step", "What should the reader do or know?")
            )
        finally:
            release_dialog()
        if text:
            recording.add(InfoStep(t=round(elapsed(), 3), text=text))
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

        if ctrl and shift:
            if key == keyboard.Key.end:
                print("Stopping.")
                return False
            if is_letter_key(key, "s"):
                threading.Thread(target=start_subtask, daemon=True).start()
                return
            if is_letter_key(key, "e"):
                end_subtask()
                return
            if is_letter_key(key, "i"):
                threading.Thread(target=add_info_step, daemon=True).start()
                return

        if key == keyboard.Key.enter:
            schedule_check("enter")

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
                print("Reading the screen to fill the popup in for you.")
            else:
                print("Install .[ocr] to have the screen, control and value filled in for you.")
        if redaction is not None and not redaction.is_empty():
            print(f"Redaction active while recording: {redaction.describe()}")
    else:
        print("Screenshots are off: build the document from a screen recording instead.")
    print("Ctrl+Shift+S subtask, Ctrl+Shift+E end subtask, Ctrl+Shift+I info step, Ctrl+Shift+End stop.")

    m_listener = mouse.Listener(on_click=on_click)
    k_listener = keyboard.Listener(on_press=on_key_press, on_release=on_key_release)

    m_listener.start()
    k_listener.start()
    try:
        k_listener.join()
    except KeyboardInterrupt:
        k_listener.stop()
    finally:
        m_listener.stop()
        with lock:
            if pending_timer is not None:
                pending_timer.cancel()
                pending_timer = None

        # A popup may still be open, or a step may be mid-capture. Wait for it,
        # so stopping never costs the step that was being filled in.
        deadline = time.time() + result_window + 30.0
        while dialog_open and time.time() < deadline:
            time.sleep(0.1)

        save_recording()
        dialogs.stop()

    return recording
