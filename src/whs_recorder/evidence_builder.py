"""Turn a recording plus a screen capture into a Word document.

The recording says what happened and in what order; the video supplies the
pixels. For each recorded step the builder picks the action frame, looks for the
frame that shows the result banner, applies the redaction rules, and hands the
lot to one of the writers in `task_guide`.
"""

import os
import json
import datetime
import re
from typing import Dict, List, Optional

import cv2

from .frame_select import FrameChoice, choose_frame, choose_result_frame
from .instructions import PREFERRED, VALUE_MODES
from .recording import STEP, Recording
from .redaction import RedactionConfig
from .task_guide import StepCapture, write_evidence_document, write_task_guide
from .utils import ensure_dir

JPEG_PARAMS = [int(cv2.IMWRITE_JPEG_QUALITY), 92]

TASK_GUIDE = "task-guide"
EVIDENCE = "evidence"
STYLES = (TASK_GUIDE, EVIDENCE)

TOAST_CAPTION = {
    "success": "Result (success message detected):",
    "error": "Result (error message detected):",
    "warning": "Result (warning message detected):",
}


def _slug(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", (name or "").strip()).strip("_")
    return slug or "Task_guide"


def _write_capture(frame, path: str, redaction: Optional[RedactionConfig]) -> str:
    if redaction is not None:
        frame = redaction.apply(frame)
    cv2.imwrite(path, frame, JPEG_PARAMS)
    return path


def _result_caption(choice: FrameChoice) -> str:
    if choice.has_toast:
        return TOAST_CAPTION.get(choice.toast.family, "Result (message detected):")
    return "Result:"


def build_evidence(
    video: str,
    markers: str,
    out_dir: str,
    title: str = None,
    skip_loading: bool = True,
    result_offsets: List[float] = None,
    redaction: Optional[RedactionConfig] = None,
    result_window: float = 2.5,
    detect_toast: bool = True,
    style: str = TASK_GUIDE,
    value_mode: str = PREFERRED,
    include_result: bool = False,
):
    """Build a Word document from a recording and its screen capture.

    `style` picks the layout: `task-guide` reproduces what D365 Task Recorder
    exports, `evidence` keeps the action/result pairing this tool started with.
    `value_mode` chooses between the recorded values and "enter a value" wording,
    as Task Recorder's preferred and example value labels do.
    """
    if style not in STYLES:
        raise ValueError(f"Unknown style {style!r} (expected one of {', '.join(STYLES)})")
    if value_mode not in VALUE_MODES:
        raise ValueError(f"Unknown value mode {value_mode!r} (expected one of {', '.join(VALUE_MODES)})")
    if result_offsets is None:
        result_offsets = [0.6, 1.2]

    ensure_dir(out_dir)

    recording = Recording.load(markers)
    outline = recording.outline(skip_loading=skip_loading)
    if not outline:
        raise RuntimeError("No steps found.")

    cap = cv2.VideoCapture(video)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 10.0

    run_stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    run_out = os.path.join(out_dir, f"run_{run_stamp}")
    ensure_dir(run_out)

    redaction_summary = redaction.describe() if redaction is not None else "none"
    if redaction is not None and not redaction.is_empty():
        print(f"Redaction active: {redaction.describe()}")

    want_result = style == EVIDENCE or include_result
    captures: Dict[int, StepCapture] = {}

    for entry in outline:
        if entry.kind != STEP:
            continue

        step = entry.node
        capture = StepCapture(node_index=entry.node_index, t=step.t)

        action = choose_frame(cap, fps, step.t)
        capture.action_mode = action.mode
        if action.frame is not None:
            capture.action_img = _write_capture(
                action.frame,
                os.path.join(run_out, f"step_{entry.number:02d}_action_{action.mode}.jpg"),
                redaction,
            )

        if want_result:
            result = choose_result_frame(
                cap,
                fps,
                step.t,
                baseline=action.frame,
                offsets=result_offsets,
                window_sec=result_window,
                use_toast_detection=detect_toast,
            )
            capture.result_mode = result.mode
            capture.result_offset = result.offset
            capture.result_toast = result.toast.family if result.has_toast else None
            capture.result_caption = _result_caption(result)
            if result.frame is not None:
                name = f"step_{entry.number:02d}_result_{result.mode}_plus{result.offset:.1f}s.jpg"
                capture.result_img = _write_capture(result.frame, os.path.join(run_out, name), redaction)

        captures[entry.node_index] = capture

    cap.release()

    if style == TASK_GUIDE:
        out_doc = os.path.join(run_out, f"{_slug(title or recording.name)}.docx")
        write_task_guide(
            recording,
            outline,
            captures,
            out_doc,
            value_mode=value_mode,
            title=title,
            include_result=include_result,
        )
    else:
        out_doc = os.path.join(run_out, "WHS_Test_Evidence.docx")
        write_evidence_document(
            recording,
            outline,
            captures,
            out_doc,
            value_mode=value_mode,
            title=title,
            video=video,
            markers=markers,
            redaction_summary=redaction_summary,
        )

    _write_manifest(
        os.path.join(run_out, "steps.json"),
        recording=recording,
        outline=outline,
        captures=captures,
        video=video,
        markers=markers,
        run_stamp=run_stamp,
        redaction_summary=redaction_summary,
        detect_toast=detect_toast,
        style=style,
        value_mode=value_mode,
        document=out_doc,
    )

    steps = sum(1 for e in outline if e.kind == STEP)
    if want_result:
        toasts = sum(1 for c in captures.values() if c.result_toast)
        print(f"Captured {steps} step(s); result message detected on {toasts}.")
    else:
        print(f"Captured {steps} step(s).")
    print("Created:", out_doc)
    return out_doc


def _write_manifest(path: str, recording, outline, captures, video, markers, run_stamp,
                    redaction_summary, detect_toast, style, value_mode, document) -> str:
    steps = []
    for entry in outline:
        capture = captures.get(entry.node_index)
        record = {
            "no": entry.number,
            "kind": entry.kind,
            "depth": entry.depth,
            "instruction": getattr(entry.node, "instruction", lambda mode: "")(value_mode),
            "title": getattr(entry.node, "title", ""),
            "note": getattr(entry.node, "note", ""),
        }
        if entry.kind == "subtask_start":
            record = {"no": None, "kind": entry.kind, "depth": entry.depth, "name": entry.node.name}
        elif capture is not None:
            record.update({
                "t": capture.t,
                "action": getattr(entry.node, "action", ""),
                "control": getattr(entry.node, "control", ""),
                "action_img": capture.action_img,
                "result_img": capture.result_img,
                "result_mode": capture.result_mode,
                "result_offset": capture.result_offset,
                "result_toast": capture.result_toast,
                "result_caption": capture.result_caption,
            })
        steps.append(record)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "recording": recording.name,
                "description": recording.description,
                "video": os.path.basename(video),
                "markers": os.path.basename(markers),
                "generated": run_stamp,
                "document": os.path.basename(document),
                "style": style,
                "value_mode": value_mode,
                "redaction": redaction_summary,
                "toast_detection": detect_toast,
                "steps": steps,
            },
            f,
            indent=2,
            ensure_ascii=False,
        )
    return path
