import os
import time
import json
import threading
from dataclasses import dataclass
from typing import Optional, List

import numpy as np
import cv2
import mss
from pynput import mouse, keyboard
import tkinter as tk
from tkinter import ttk


@dataclass
class StepLabel:
    title: str
    notes: str = ""
    is_loading: bool = False


def run_marker_recorder(
    out_path: str,
    monitor_index: int = 1,
    min_gap_sec: float = 0.75,
    post_delay_sec: float = 0.30,
    diff_threshold: float = 7.5,
):
    """
    Smart marker recorder with manual step labeling popup.
    """

    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    start_epoch = time.time()
    markers = []
    last_mark_t = 0.0
    pressed = set()
    pending_timer: Optional[threading.Timer] = None
    lock = threading.Lock()

    sct = mss.mss()
    monitor = sct.monitors[monitor_index] if monitor_index else sct.monitors[0]

    def grab_signature():
        img = np.array(sct.grab(monitor))[:, :, :3]
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, (160, 90), interpolation=cv2.INTER_AREA)
        return gray

    def mean_abs_diff(a, b):
        return float(np.mean(np.abs(a.astype(np.float32) - b.astype(np.float32))))

    last_sig = grab_signature()

    def ask_step_label(step_no: int, reason: str, diff: float) -> Optional[StepLabel]:
        result = [None]

        root = tk.Tk()
        root.title(f"Step {step_no}")
        root.attributes("-topmost", True)
        root.resizable(False, False)

        frm = ttk.Frame(root, padding=12)
        frm.grid()

        ttk.Label(frm, text=f"Step {step_no} ({reason}, diff={diff:.1f})").grid(row=0, column=0, columnspan=2)

        ttk.Label(frm, text="Step title:").grid(row=1, column=0, sticky="w")
        title_var = tk.StringVar()
        entry = ttk.Entry(frm, textvariable=title_var, width=45)
        entry.grid(row=2, column=0, columnspan=2)
        entry.focus_set()

        ttk.Label(frm, text="Notes:").grid(row=3, column=0, sticky="w")
        notes = tk.Text(frm, width=45, height=4)
        notes.grid(row=4, column=0, columnspan=2)

        loading_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            frm,
            text="Loading / transition screen",
            variable=loading_var,
        ).grid(row=5, column=0, columnspan=2, sticky="w")

        def on_ok():
            t = title_var.get().strip()
            if not t:
                return
            result[0] = StepLabel(
                title=t,
                notes=notes.get("1.0", "end").strip(),
                is_loading=loading_var.get(),
            )
            root.destroy()

        def on_cancel():
            root.destroy()

        ttk.Button(frm, text="OK", command=on_ok).grid(row=6, column=0)
        ttk.Button(frm, text="Cancel", command=on_cancel).grid(row=6, column=1)

        root.mainloop()
        return result[0]

    def save_markers():
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "start_epoch": start_epoch,
                    "monitor_index": monitor_index,
                    "diff_threshold": diff_threshold,
                    "markers": markers,
                },
                f,
                indent=2,
                ensure_ascii=False,
            )
        print(f"Saved {len(markers)} markers to: {out_path}")

    def maybe_mark(reason: str):
        nonlocal last_mark_t, last_sig, pending_timer

        with lock:
            pending_timer = None

        t_now = time.time() - start_epoch
        if t_now - last_mark_t < min_gap_sec:
            return

        new_sig = grab_signature()
        diff = mean_abs_diff(new_sig, last_sig)

        if diff < diff_threshold:
            return

        step_no = len(markers) + 1
        label = ask_step_label(step_no, reason, diff)
        if label is None:
            last_sig = new_sig
            return

        last_mark_t = t_now
        last_sig = new_sig

        markers.append(
            {
                "t": round(t_now, 3),
                "reason": reason,
                "diff": round(diff, 2),
                "title": label.title,
                "notes": label.notes,
                "is_loading": label.is_loading,
            }
        )

        print(f"Marked step {step_no}: {label.title}")

    def schedule_check(reason: str):
        nonlocal pending_timer
        with lock:
            if pending_timer is not None:
                return
            pending_timer = threading.Timer(post_delay_sec, maybe_mark, args=(reason,))
            pending_timer.start()

    def on_click(x, y, button, is_pressed):
        if is_pressed:
            schedule_check("mouse_click")

    def on_key_press(key):
        pressed.add(key)

        if key == keyboard.Key.enter:
            schedule_check("enter")

        ctrl = keyboard.Key.ctrl_l in pressed or keyboard.Key.ctrl_r in pressed
        shift = (
            keyboard.Key.shift_l in pressed
            or keyboard.Key.shift_r in pressed
        )

        if ctrl and shift and key == keyboard.Key.end:
            save_markers()
            return False

    def on_key_release(key):
        if key in pressed:
            pressed.remove(key)

    print("Marker recorder running (Ctrl+Shift+End to stop).")

    m_listener = mouse.Listener(on_click=on_click)
    k_listener = keyboard.Listener(on_press=on_key_press, on_release=on_key_release)

    m_listener.start()
    k_listener.start()
    k_listener.join()
    m_listener.stop()
