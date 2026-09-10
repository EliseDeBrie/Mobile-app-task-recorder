"""The recorder: watch the screen, and ask what each action was.

D365 Task Recorder can name a step by itself because every control tells it what
was clicked and with what value. Nothing on a handheld does that, so this
recorder asks. When a click or an Enter visibly changes the screen it raises a
popup carrying the same fields a Task Recorder step holds - the action, the
control, the value, and the title and note annotations - and shows the sentence
those fields will produce in the guide.

Gestures, mirroring the Task Recorder pane:

* ``Ctrl+Shift+S`` start a subtask
* ``Ctrl+Shift+E`` end the current subtask
* ``Ctrl+Shift+I`` add an info step
* ``Ctrl+Shift+End`` stop and save
"""

import time
import threading
import tkinter as tk
from tkinter import ttk
from typing import Optional

import numpy as np
import cv2
import mss
from pynput import mouse, keyboard

from .instructions import ACTION_CHOICES, ACTION_LABELS, ACTIONS, PREFERRED, render_instruction
from .recording import InfoStep, Recording, Step, SubtaskEnd, SubtaskStart
from .utils import ensure_parent_dir, is_letter_key, mean_abs_diff

DEFAULT_ACTION_LABEL = ACTION_CHOICES[0][0]


def _ask_step(step_no: int, reason: str, diff: float) -> Optional[Step]:
    """Popup for one recorded action, previewing the sentence it will produce."""
    result = [None]

    root = tk.Tk()
    root.title(f"Step {step_no}")
    root.attributes("-topmost", True)
    root.resizable(False, False)

    frm = ttk.Frame(root, padding=12)
    frm.grid()

    ttk.Label(frm, text=f"Step {step_no} ({reason}, diff={diff:.1f})").grid(
        row=0, column=0, columnspan=2, sticky="w"
    )

    ttk.Label(frm, text="Action:").grid(row=1, column=0, sticky="w", pady=(8, 0))
    action_var = tk.StringVar(value=DEFAULT_ACTION_LABEL)
    action_box = ttk.Combobox(
        frm, textvariable=action_var, values=[label for label, _ in ACTION_CHOICES],
        state="readonly", width=42,
    )
    action_box.grid(row=2, column=0, columnspan=2, sticky="w")

    ttk.Label(frm, text="Button, field or page name:").grid(row=3, column=0, sticky="w", pady=(8, 0))
    control_var = tk.StringVar()
    control_entry = ttk.Entry(frm, textvariable=control_var, width=45)
    control_entry.grid(row=4, column=0, columnspan=2)
    control_entry.focus_set()

    ttk.Label(frm, text="Value (for a scan or an entry):").grid(row=5, column=0, sticky="w", pady=(8, 0))
    value_var = tk.StringVar()
    ttk.Entry(frm, textvariable=value_var, width=45).grid(row=6, column=0, columnspan=2)

    ttk.Label(frm, text="Step reads as:").grid(row=7, column=0, sticky="w", pady=(8, 0))
    preview_var = tk.StringVar()
    preview = ttk.Label(frm, textvariable=preview_var, width=45, wraplength=330, foreground="#1a5fb4")
    preview.grid(row=8, column=0, columnspan=2, sticky="w")

    ttk.Label(frm, text="Title (shown above the step):").grid(row=9, column=0, sticky="w", pady=(8, 0))
    title_var = tk.StringVar()
    ttk.Entry(frm, textvariable=title_var, width=45).grid(row=10, column=0, columnspan=2)

    ttk.Label(frm, text="Note (shown after the step):").grid(row=11, column=0, sticky="w", pady=(8, 0))
    note = tk.Text(frm, width=45, height=3)
    note.grid(row=12, column=0, columnspan=2)

    loading_var = tk.BooleanVar(value=False)
    ttk.Checkbutton(frm, text="Loading / transition screen", variable=loading_var).grid(
        row=13, column=0, columnspan=2, sticky="w", pady=(8, 0)
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
            return
        result[0] = Step(
            action=action,
            control=control,
            value=value_var.get().strip(),
            title=title_var.get().strip(),
            note=note.get("1.0", "end").strip(),
            is_loading=loading_var.get(),
        )
        root.destroy()

    def on_skip():
        root.destroy()

    buttons = ttk.Frame(frm)
    buttons.grid(row=14, column=0, columnspan=2, pady=(10, 0), sticky="e")
    ttk.Button(buttons, text="OK", command=on_ok).grid(row=0, column=0, padx=4)
    ttk.Button(buttons, text="Skip", command=on_skip).grid(row=0, column=1)
    root.bind("<Return>", lambda _e: on_ok())
    root.bind("<Escape>", lambda _e: on_skip())

    root.mainloop()
    return result[0]


def _ask_text(window_title: str, prompt: str) -> Optional[str]:
    """Single-line prompt used by the subtask and info-step gestures."""
    result = [None]

    root = tk.Tk()
    root.title(window_title)
    root.attributes("-topmost", True)
    root.resizable(False, False)

    frm = ttk.Frame(root, padding=12)
    frm.grid()
    ttk.Label(frm, text=prompt).grid(row=0, column=0, columnspan=2, sticky="w")

    text_var = tk.StringVar()
    entry = ttk.Entry(frm, textvariable=text_var, width=45)
    entry.grid(row=1, column=0, columnspan=2, pady=(6, 0))
    entry.focus_set()

    def on_ok():
        value = text_var.get().strip()
        if value:
            result[0] = value
        root.destroy()

    ttk.Button(frm, text="OK", command=on_ok).grid(row=2, column=0, pady=(10, 0))
    ttk.Button(frm, text="Cancel", command=root.destroy).grid(row=2, column=1, pady=(10, 0))
    root.bind("<Return>", lambda _e: on_ok())
    root.bind("<Escape>", lambda _e: root.destroy())

    root.mainloop()
    return result[0]


def run_marker_recorder(
    out_path: str,
    monitor_index: int = 1,
    min_gap_sec: float = 0.75,
    post_delay_sec: float = 0.30,
    diff_threshold: float = 7.5,
    name: str = "",
    description: str = "",
):
    """Record a task recording for a handheld process."""

    ensure_parent_dir(out_path)

    recording = Recording(
        name=name or "Untitled recording",
        description=description,
        start_epoch=time.time(),
        monitor_index=monitor_index,
        diff_threshold=diff_threshold,
    )

    saved = False
    last_mark_t = 0.0
    pressed = set()
    pending_timer: Optional[threading.Timer] = None
    dialog_open = False
    lock = threading.Lock()

    sct = mss.mss()
    monitor = sct.monitors[monitor_index] if monitor_index else sct.monitors[0]

    def grab_signature():
        img = np.array(sct.grab(monitor))[:, :, :3]
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        return cv2.resize(gray, (160, 90), interpolation=cv2.INTER_AREA)

    last_sig = grab_signature()

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
        nonlocal saved
        saved = True
        recording.save(out_path)
        steps = len(recording.steps)
        print(f"Saved {steps} step(s) to: {out_path}")

    def maybe_mark(reason: str):
        nonlocal last_mark_t, last_sig, pending_timer

        with lock:
            pending_timer = None
            if dialog_open:
                return

        t_now = elapsed()
        if t_now - last_mark_t < min_gap_sec:
            return

        new_sig = grab_signature()
        diff = mean_abs_diff(new_sig, last_sig)
        if diff < diff_threshold:
            return

        if not claim_dialog():
            return
        try:
            step = _ask_step(len(recording.steps) + 1, reason, diff)
        finally:
            release_dialog()

        if step is None:
            last_sig = new_sig
            return

        step.t = round(t_now, 3)
        step.reason = reason
        step.diff = round(diff, 2)

        last_mark_t = t_now
        last_sig = new_sig
        recording.add(step)
        print(f"Step {len(recording.steps)}: {step.instruction(PREFERRED)}")

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
            subtask_name = _ask_text("Start subtask", "Name of the subtask:")
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
            text = _ask_text("Info step", "What should the reader do or know?")
        finally:
            release_dialog()
        if text:
            recording.add(InfoStep(t=round(elapsed(), 3), text=text))
            print(f"Info step: {text}")

    def on_click(x, y, button, is_pressed):
        if is_pressed:
            schedule_check("mouse_click")

    def on_key_press(key):
        pressed.add(key)

        ctrl = keyboard.Key.ctrl_l in pressed or keyboard.Key.ctrl_r in pressed
        shift = keyboard.Key.shift_l in pressed or keyboard.Key.shift_r in pressed

        if ctrl and shift:
            if key == keyboard.Key.end:
                save_recording()
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
        if not saved:
            # The recorder was stopped some other way - never lose the recording.
            save_recording()

    return recording
