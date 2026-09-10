import json
import os

import cv2
import numpy as np
import pytest

from conftest import add_banner, make_screen

from whs_recorder.evidence_builder import build_evidence
from whs_recorder.redaction import RedactionConfig

GREEN = (0, 200, 0)


@pytest.fixture
def recording(tmp_path):
    """A 4-second recording where a success banner shows 0.9s after the marker."""
    path = tmp_path / "run.mp4"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10.0, (360, 640))
    if not writer.isOpened():
        pytest.skip("No video writer available in this environment")

    for i in range(40):
        frame = make_screen(seed=i)
        if 24 <= i <= 28:
            frame = add_banner(frame, GREEN)
        writer.write(frame)
    writer.release()
    return str(path)


@pytest.fixture
def markers(tmp_path):
    path = tmp_path / "step_markers.json"
    path.write_text(
        json.dumps(
            {
                "start_epoch": 0,
                "markers": [
                    {"t": 1.5, "title": "Scan licence plate", "notes": "LP scan", "is_loading": False},
                    {"t": 2.4, "title": "Waiting", "notes": "", "is_loading": True},
                ],
            }
        ),
        encoding="utf-8",
    )
    return str(path)


def read_manifest(out_dir):
    run_dir = os.path.join(out_dir, sorted(os.listdir(out_dir))[0])
    with open(os.path.join(run_dir, "steps.json"), encoding="utf-8") as f:
        return run_dir, json.load(f)


def test_build_produces_a_document_and_manifest(recording, markers, tmp_path):
    out_dir = tmp_path / "out"
    doc = build_evidence(video=recording, markers=markers, out_dir=str(out_dir), skip_loading=False)

    assert os.path.exists(doc)
    run_dir, manifest = read_manifest(str(out_dir))
    assert manifest["toast_detection"] is True
    assert manifest["redaction"] == "none"
    assert [s["title"] for s in manifest["steps"]] == ["Scan licence plate", "Waiting"]


def test_loading_markers_are_skipped_on_request(recording, markers, tmp_path):
    out_dir = tmp_path / "out"
    build_evidence(video=recording, markers=markers, out_dir=str(out_dir), skip_loading=True)

    _, manifest = read_manifest(str(out_dir))
    assert [s["title"] for s in manifest["steps"]] == ["Scan licence plate"]


def test_result_frame_lands_on_the_banner(recording, markers, tmp_path):
    out_dir = tmp_path / "out"
    build_evidence(video=recording, markers=markers, out_dir=str(out_dir), skip_loading=True)

    run_dir, manifest = read_manifest(str(out_dir))
    step = manifest["steps"][0]

    assert step["result_toast"] == "success"
    assert step["result_mode"] == "toast"
    assert step["result_caption"] == "Result (success message detected):"
    assert 0.8 <= step["result_offset"] <= 1.4

    saved = cv2.imread(step["result_img"])
    assert (saved[560:600, :, 1] > 120).mean() > 0.8  # the green banner really is in the file


def test_toast_detection_can_be_disabled(recording, markers, tmp_path):
    out_dir = tmp_path / "out"
    build_evidence(
        video=recording,
        markers=markers,
        out_dir=str(out_dir),
        skip_loading=True,
        detect_toast=False,
        result_offsets=[0.3],
    )

    _, manifest = read_manifest(str(out_dir))
    assert manifest["steps"][0]["result_toast"] is None
    assert manifest["steps"][0]["result_offset"] == 0.3


def test_redaction_is_applied_to_every_saved_screenshot(recording, markers, tmp_path):
    out_dir = tmp_path / "out"
    redaction = RedactionConfig.from_dict({"regions": [{"name": "user", "box": [0.0, 0.0, 1.0, 0.1]}]})

    build_evidence(
        video=recording, markers=markers, out_dir=str(out_dir), skip_loading=True, redaction=redaction
    )

    run_dir, manifest = read_manifest(str(out_dir))
    assert manifest["redaction"] == "1 region rule(s)"

    images = [p for p in (manifest["steps"][0]["action_img"], manifest["steps"][0]["result_img"]) if p]
    assert images
    for path in images:
        assert (cv2.imread(path)[0:60] < 25).all()


def test_missing_markers_are_rejected(recording, tmp_path):
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"markers": []}), encoding="utf-8")

    with pytest.raises(RuntimeError, match="No markers"):
        build_evidence(video=recording, markers=str(empty), out_dir=str(tmp_path / "out"))


def test_unreadable_video_is_rejected(markers, tmp_path):
    with pytest.raises(RuntimeError, match="Cannot open video"):
        build_evidence(video=str(tmp_path / "nope.mp4"), markers=markers, out_dir=str(tmp_path / "out"))
