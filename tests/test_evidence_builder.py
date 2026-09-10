import json
import os

import cv2
import pytest
from docx import Document

from conftest import add_banner, make_screen

from whs_recorder.evidence_builder import EVIDENCE, TASK_GUIDE, build_evidence
from whs_recorder.instructions import EXAMPLE
from whs_recorder.recording import InfoStep, Recording, Step, SubtaskEnd, SubtaskStart
from whs_recorder.redaction import RedactionConfig

GREEN = (0, 200, 0)


@pytest.fixture
def recording_path(tmp_path):
    r = Recording(name="Receive a purchase order line", description="WHS mobile receiving.")
    r.add(SubtaskStart(t=0.2, name="Open the work"))
    r.add(Step(t=1.5, action="scan", control="LP", value="LP000123", note="LP from the pallet label"))
    r.add(SubtaskEnd(t=2.0))
    r.add(Step(t=2.4, action="tap", control="OK", is_loading=True))
    r.add(Step(t=4.4, action="enter", control="Quantity", value="12"))
    r.add(InfoStep(t=5.4, text="Move the pallet to the staging lane"))
    path = tmp_path / "recording.json"
    r.save(str(path))
    return str(path)


@pytest.fixture
def video(tmp_path):
    """A 6-second recording with a success banner 0.9s after the first step."""
    path = tmp_path / "run.mp4"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10.0, (360, 640))
    if not writer.isOpened():
        pytest.skip("No video writer available in this environment")

    for i in range(60):
        frame = make_screen(seed=i)
        if 24 <= i <= 28:
            frame = add_banner(frame, GREEN)
        writer.write(frame)
    writer.release()
    return str(path)


def read_run(out_dir):
    run_dir = os.path.join(out_dir, sorted(os.listdir(out_dir))[0])
    with open(os.path.join(run_dir, "steps.json"), encoding="utf-8") as f:
        return run_dir, json.load(f)


def doc_text(path):
    return [p.text for p in Document(path).paragraphs if p.text]


def test_task_guide_is_the_default_document(video, recording_path, tmp_path):
    out_dir = tmp_path / "out"
    doc = build_evidence(video=video, markers=recording_path, out_dir=str(out_dir), skip_loading=True)

    assert os.path.basename(doc) == "Receive_a_purchase_order_line.docx"
    body = doc_text(doc)
    assert body[0] == "Receive a purchase order line"
    assert "Open the work" in body
    assert "1. In the LP field, scan 'LP000123'." in body
    assert "2. In the Quantity field, enter '12'." in body
    assert "3. Move the pallet to the staging lane." in body


def test_the_manifest_records_the_generated_instructions(video, recording_path, tmp_path):
    out_dir = tmp_path / "out"
    build_evidence(video=video, markers=recording_path, out_dir=str(out_dir), skip_loading=True)

    _, manifest = read_run(str(out_dir))

    assert manifest["recording"] == "Receive a purchase order line"
    assert manifest["style"] == TASK_GUIDE
    assert manifest["value_mode"] == "preferred"
    assert [s["kind"] for s in manifest["steps"]] == ["subtask_start", "step", "step", "info"]
    assert manifest["steps"][1]["instruction"] == "In the LP field, scan 'LP000123'."
    assert manifest["steps"][1]["control"] == "LP"
    assert manifest["steps"][3].get("action_img") is None


def test_example_values_change_the_wording(video, recording_path, tmp_path):
    out_dir = tmp_path / "out"
    doc = build_evidence(
        video=video, markers=recording_path, out_dir=str(out_dir), skip_loading=True, value_mode=EXAMPLE
    )

    assert "1. In the LP field, scan the value from the label." in doc_text(doc)


def test_a_step_screenshot_is_taken_for_every_step_but_not_for_info_steps(video, recording_path, tmp_path):
    out_dir = tmp_path / "out"
    doc = build_evidence(video=video, markers=recording_path, out_dir=str(out_dir), skip_loading=True)

    assert len(Document(doc).inline_shapes) == 2


def test_loading_steps_are_skipped_on_request(video, recording_path, tmp_path):
    out_dir = tmp_path / "out"
    build_evidence(video=video, markers=recording_path, out_dir=str(out_dir), skip_loading=False)

    _, manifest = read_run(str(out_dir))
    assert [s["no"] for s in manifest["steps"] if s["kind"] == "step"] == [1, 2, 3]


def test_task_guide_can_include_the_result_screenshot(video, recording_path, tmp_path):
    out_dir = tmp_path / "out"
    doc = build_evidence(
        video=video, markers=recording_path, out_dir=str(out_dir), skip_loading=True, include_result=True
    )

    body = doc_text(doc)
    assert "Result (success message detected):" in body
    assert len(Document(doc).inline_shapes) > 2


def test_evidence_style_still_pairs_action_and_result(video, recording_path, tmp_path):
    out_dir = tmp_path / "out"
    doc = build_evidence(
        video=video, markers=recording_path, out_dir=str(out_dir), skip_loading=True, style=EVIDENCE
    )

    assert os.path.basename(doc) == "WHS_Test_Evidence.docx"
    body = doc_text(doc)
    assert "Action:" in body
    assert "1. In the LP field, scan 'LP000123'." in body

    _, manifest = read_run(str(out_dir))
    step = manifest["steps"][1]
    assert step["result_toast"] == "success"
    assert step["result_mode"] == "toast"
    assert 0.8 <= step["result_offset"] <= 1.4
    saved = cv2.imread(step["result_img"])
    assert (saved[560:600, :, 1] > 120).mean() > 0.8


def test_task_guide_skips_the_result_scan_it_does_not_need(video, recording_path, tmp_path):
    out_dir = tmp_path / "out"
    build_evidence(video=video, markers=recording_path, out_dir=str(out_dir), skip_loading=True)

    run_dir, manifest = read_run(str(out_dir))
    assert not any("result" in name for name in os.listdir(run_dir))
    assert manifest["steps"][1]["result_img"] is None


def test_redaction_is_applied_to_every_saved_screenshot(video, recording_path, tmp_path):
    out_dir = tmp_path / "out"
    redaction = RedactionConfig.from_dict({"regions": [{"name": "user", "box": [0.0, 0.0, 1.0, 0.1]}]})

    build_evidence(
        video=video, markers=recording_path, out_dir=str(out_dir), skip_loading=True,
        redaction=redaction, style=EVIDENCE,
    )

    _, manifest = read_run(str(out_dir))
    assert manifest["redaction"] == "1 region rule(s)"
    images = [manifest["steps"][1]["action_img"], manifest["steps"][1]["result_img"]]
    for path in images:
        assert (cv2.imread(path)[0:60] < 25).all()


def test_a_legacy_markers_file_still_builds(video, tmp_path):
    markers = tmp_path / "step_markers.json"
    markers.write_text(
        json.dumps({"markers": [{"t": 1.5, "title": "Scan the licence plate", "notes": "", "is_loading": False}]}),
        encoding="utf-8",
    )

    doc = build_evidence(video=video, markers=str(markers), out_dir=str(tmp_path / "out"))

    assert "1. Scan the licence plate." in doc_text(doc)


def test_an_empty_recording_is_rejected(video, tmp_path):
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"nodes": []}), encoding="utf-8")

    with pytest.raises(RuntimeError, match="No steps"):
        build_evidence(video=video, markers=str(empty), out_dir=str(tmp_path / "out"))


def test_unreadable_video_is_rejected(recording_path, tmp_path):
    with pytest.raises(RuntimeError, match="Cannot open video"):
        build_evidence(video=str(tmp_path / "nope.mp4"), markers=recording_path, out_dir=str(tmp_path / "out"))


def test_unknown_style_and_value_mode_are_rejected(video, recording_path, tmp_path):
    with pytest.raises(ValueError, match="Unknown style"):
        build_evidence(video=video, markers=recording_path, out_dir=str(tmp_path / "o"), style="fancy")

    with pytest.raises(ValueError, match="Unknown value mode"):
        build_evidence(video=video, markers=recording_path, out_dir=str(tmp_path / "o"), value_mode="loud")
