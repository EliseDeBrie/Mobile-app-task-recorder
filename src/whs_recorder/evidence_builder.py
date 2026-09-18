"""Turn a recording into a Word document.

The pixels come from one of two places. A recording made with screenshots on
already carries them, captured from the app region at each step, and the builder
just redacts and lays them out. Otherwise it falls back to a screen recording:
for each step it picks the action frame, looks for the frame showing the result
banner, and crops to the app region if the video covers the whole screen.
"""

import os
import json
import datetime
import shutil
from typing import Dict, List, Optional

import cv2

from .frame_select import FrameChoice, choose_frame, choose_result_frame
from .instructions import PREFERRED, VALUE_MODES
from .recording import STEP, Recording
from .redaction import RedactionConfig
from .task_guide import StepCapture, write_evidence_document, write_task_guide
from .utils import ensure_dir, read_image, safe_filename, write_image

JPEG_PARAMS = [int(cv2.IMWRITE_JPEG_QUALITY), 92]

TASK_GUIDE = "task-guide"
EVIDENCE = "evidence"
STYLES = (TASK_GUIDE, EVIDENCE)

TOAST_CAPTION = {
    "success": "Result (success message detected):",
    "error": "Result (error message detected):",
    "warning": "Result (warning message detected):",
}


def _write_capture(frame, path: str, redaction: Optional[RedactionConfig]) -> str:
    if redaction is not None:
        frame = redaction.apply(frame)
    return write_image(path, frame, JPEG_PARAMS)


def _result_caption(choice: FrameChoice) -> str:
    if choice.has_toast:
        return TOAST_CAPTION.get(choice.toast.family, "Result (message detected):")
    return "Result:"


def _caption_for_toast(family: str) -> str:
    if not family:
        return "Result:"
    return TOAST_CAPTION.get(family, "Result (message detected):")


def _crop_to_region(frame, region):
    """Crop a video frame to the app region, when the video covers the screen.

    A video that is already the size of the region was captured of the app
    window itself, and one too small to contain the region is not a full-screen
    capture either. Both are left alone.
    """
    if region is None or frame is None:
        return frame
    height, width = frame.shape[:2]
    if (width, height) == (region.width, region.height):
        return frame
    if width < region.right or height < region.bottom:
        return frame
    return region.crop(frame)


def build_evidence(
    markers: str,
    out_dir: str,
    video: str = "",
    title: Optional[str] = None,
    skip_loading: bool = True,
    result_offsets: Optional[List[float]] = None,
    redaction: Optional[RedactionConfig] = None,
    result_window: float = 2.5,
    detect_toast: bool = True,
    style: str = TASK_GUIDE,
    value_mode: str = PREFERRED,
    include_result: bool = False,
    document: Optional[str] = None,
):
    """Build a Word document from a recording and its screen capture.

    `style` picks the layout: `task-guide` reproduces what D365 Task Recorder
    exports, `evidence` keeps the action/result pairing this tool started with.
    `value_mode` chooses between the recorded values and "enter a value" wording,
    as Task Recorder's preferred and example value labels do.

    Every build goes into a run folder of its own under `out_dir`, with the
    pictures and a manifest beside the document, so that no build overwrites
    another. `document` is for the person who wants one file with a fixed name:
    the finished document is also placed there, replacing the previous one.
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

    cap = None
    fps = 10.0
    if video:
        cap = cv2.VideoCapture(video)
        if not cap.isOpened():
            hint = ""
            if not video.isascii():
                # OpenCV reads video paths through the C runtime, which on
                # Windows cannot see characters outside the active code page.
                hint = " (try a path without accented characters)"
            raise RuntimeError(f"Cannot open video: {video}{hint}")
        fps = cap.get(cv2.CAP_PROP_FPS) or 10.0
    elif not recording.has_screenshots:
        raise RuntimeError(
            "This recording holds no screenshots, so a screen recording is needed: pass --video."
        )

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

        if step.action_img:
            _use_recorded_screenshots(recording, step, entry, capture, run_out, redaction, want_result)
        elif cap is not None:
            _use_video_frames(
                recording, step, entry, capture, run_out, redaction, want_result, cap, fps,
                result_offsets, result_window, detect_toast,
            )

        captures[entry.node_index] = capture

    if cap is not None:
        cap.release()

    if style == TASK_GUIDE:
        out_doc = os.path.join(run_out, f"{safe_filename(title or recording.name)}.docx")
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

    if document:
        ensure_dir(os.path.dirname(os.path.abspath(document)))
        try:
            shutil.copyfile(out_doc, document)
        except OSError as exc:
            # Word holding the previous copy open is the usual reason. The
            # build is not lost - it is in the run folder - but say so.
            raise RuntimeError(
                f"The document was built but could not be placed at {document}: {exc}. "
                f"Close it if it is open, then build again. This build is at {out_doc}"
            ) from exc
        print("Document:", document)
    return out_doc


def _use_recorded_screenshots(recording, step, entry, capture, run_out, redaction, want_result) -> None:
    """Lay out the screenshots the recorder already captured from the app region."""
    action_frame = read_image(recording.image_path(step.action_img))
    if action_frame is not None:
        capture.action_mode = "recorded"
        capture.action_img = _write_capture(
            action_frame, os.path.join(run_out, f"step_{entry.number:02d}_action.jpg"), redaction
        )

    if not want_result or not step.result_img:
        return

    result_frame = read_image(recording.image_path(step.result_img))
    if result_frame is None:
        return

    capture.result_mode = "recorded"
    capture.result_toast = step.result_toast or None
    capture.result_caption = _caption_for_toast(step.result_toast)
    capture.result_img = _write_capture(
        result_frame, os.path.join(run_out, f"step_{entry.number:02d}_result.jpg"), redaction
    )


def _use_video_frames(recording, step, entry, capture, run_out, redaction, want_result, cap, fps,
                      result_offsets, result_window, detect_toast) -> None:
    """Pick this step's frames out of a screen recording."""
    action = choose_frame(cap, fps, step.t)
    capture.action_mode = action.mode
    action_frame = _crop_to_region(action.frame, recording.region)
    if action_frame is not None:
        capture.action_img = _write_capture(
            action_frame,
            os.path.join(run_out, f"step_{entry.number:02d}_action_{action.mode}.jpg"),
            redaction,
        )

    if not want_result:
        return

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

    result_frame = _crop_to_region(result.frame, recording.region)
    if result_frame is not None:
        name = f"step_{entry.number:02d}_result_{result.mode}_plus{result.offset:.1f}s.jpg"
        capture.result_img = _write_capture(result_frame, os.path.join(run_out, name), redaction)


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
            "screen": getattr(entry.node, "screen", ""),
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
                # File names, not full paths: the manifest sits beside the
                # pictures, and the folder gets zipped and sent on.
                "action_img": os.path.basename(capture.action_img) if capture.action_img else None,
                "result_img": os.path.basename(capture.result_img) if capture.result_img else None,
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
                "video": os.path.basename(video) if video else "",
                "region": recording.region.describe() if recording.region else "full screen",
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
