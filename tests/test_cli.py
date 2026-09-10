import json

import cv2
import pytest

from conftest import make_screen

from whs_recorder import cli
from whs_recorder.evidence_builder import EVIDENCE, TASK_GUIDE
from whs_recorder.instructions import EXAMPLE, PREFERRED
from whs_recorder.recording import InfoStep, Recording, Step, SubtaskEnd, SubtaskStart


@pytest.fixture
def recording_path(tmp_path):
    r = Recording(name="Receive a purchase order line", description="WHS mobile receiving.")
    r.add(SubtaskStart(t=0.2, name="Open the work"))
    r.add(Step(t=1.5, action="scan", control="LP", value="LP000123", title="Check the label",
               note="Reprint a damaged label."))
    r.add(SubtaskEnd(t=2.0))
    r.add(Step(t=3.0, action="tap", control="OK", is_loading=True))
    r.add(InfoStep(t=4.0, text="Move the pallet to the staging lane"))
    path = tmp_path / "recording.json"
    r.save(str(path))
    return str(path)


def test_build_defaults():
    args = cli.build_parser().parse_args(["build", "--video", "v.mp4", "--markers", "m.json", "--out", "o"])

    assert args.style == TASK_GUIDE
    assert args.values == PREFERRED
    assert args.with_result is False
    assert args.result_window == 2.5
    assert args.no_toast is False
    assert args.redact is None


def test_build_passes_the_options_through(monkeypatch, tmp_path):
    config = tmp_path / "r.json"
    config.write_text(json.dumps({"regions": [{"name": "r", "box": [0, 0, 1, 0.1]}]}), encoding="utf-8")

    captured = {}
    monkeypatch.setattr(cli, "build_evidence", lambda **kwargs: captured.update(kwargs))

    cli.main([
        "build", "--video", "v.mp4", "--markers", "m.json", "--out", "o",
        "--redact", str(config), "--result-window", "4", "--no-toast", "--skip-loading",
        "--style", "evidence", "--values", "example", "--with-result", "--title", "UAT evidence",
    ])

    assert captured["style"] == EVIDENCE
    assert captured["value_mode"] == EXAMPLE
    assert captured["include_result"] is True
    assert captured["title"] == "UAT evidence"
    assert captured["detect_toast"] is False
    assert captured["result_window"] == 4.0
    assert captured["skip_loading"] is True
    assert captured["result_offsets"] == [0.6, 1.2]
    assert captured["redaction"].describe() == "1 region rule(s)"


def test_build_without_a_redaction_config(monkeypatch):
    captured = {}
    monkeypatch.setattr(cli, "build_evidence", lambda **kwargs: captured.update(kwargs))

    cli.main(["build", "--video", "v.mp4", "--markers", "m.json", "--out", "o"])

    assert captured["redaction"] is None
    assert captured["detect_toast"] is True
    assert captured["title"] is None


def test_an_unknown_style_is_refused_by_the_parser():
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(
            ["build", "--video", "v", "--markers", "m", "--out", "o", "--style", "fancy"]
        )


def test_mark_accepts_a_recording_name_and_description():
    args = cli.build_parser().parse_args(
        ["mark", "--out", "r.json", "--name", "Receiving", "--description", "How we receive."]
    )
    assert args.name == "Receiving"
    assert args.description == "How we receive."


def test_preview_prints_the_guide_text(recording_path, capsys):
    cli.main(["preview", "--markers", recording_path, "--skip-loading"])

    out = capsys.readouterr().out
    assert "Receive a purchase order line" in out
    assert "[Open the work]" in out
    assert "Check the label" in out
    assert "1. In the LP field, scan 'LP000123'." in out
    assert "(Reprint a damaged label.)" in out
    assert "2. Move the pallet to the staging lane." in out
    assert "Tap OK." not in out  # the loading step is skipped


def test_preview_can_show_example_values(recording_path, capsys):
    cli.main(["preview", "--markers", recording_path, "--values", "example"])

    assert "In the LP field, scan the value from the label." in capsys.readouterr().out


def test_redact_preview_writes_a_redacted_image(tmp_path, capsys):
    image = tmp_path / "shot.png"
    cv2.imwrite(str(image), make_screen())
    config = tmp_path / "r.json"
    config.write_text(json.dumps({"regions": [{"name": "user", "box": [0, 0, 1, 0.1]}]}), encoding="utf-8")
    out = tmp_path / "preview" / "shot.png"

    cli.main(["redact-preview", "--image", str(image), "--redact", str(config), "--out", str(out)])

    assert (cv2.imread(str(out))[0:60] < 25).all()
    assert "1 region rule(s)" in capsys.readouterr().out


def test_redact_preview_labels_on_request(tmp_path):
    image = tmp_path / "shot.png"
    cv2.imwrite(str(image), make_screen())
    config = tmp_path / "r.json"
    config.write_text(json.dumps({"regions": [{"name": "user", "box": [0, 0, 1, 0.1]}]}), encoding="utf-8")
    out = tmp_path / "shot_out.png"

    cli.main(["redact-preview", "--image", str(image), "--redact", str(config), "--out", str(out), "--label"])

    result = cv2.imread(str(out))
    assert ((result[:, :, 2] > 200) & (result[:, :, 1] < 60)).any()


def test_redact_preview_rejects_an_unreadable_image(tmp_path):
    config = tmp_path / "r.json"
    config.write_text(json.dumps({"regions": [{"name": "r", "box": [0, 0, 1, 0.1]}]}), encoding="utf-8")

    with pytest.raises(SystemExit, match="Cannot read image"):
        cli.main([
            "redact-preview", "--image", str(tmp_path / "nope.png"),
            "--redact", str(config), "--out", str(tmp_path / "o.png"),
        ])


def test_mark_defaults_to_dragging_out_a_region():
    args = cli.build_parser().parse_args(["mark", "--out", "r.json"])

    assert args.region == "select"
    assert args.no_screenshots is False
    assert args.result_window == 2.5
    assert args.redact is None


def test_mark_accepts_a_typed_region_and_a_window():
    parser = cli.build_parser()
    assert parser.parse_args(["mark", "--out", "r.json", "--region", "100,80,720,1280"]).region == (
        "100,80,720,1280"
    )
    assert parser.parse_args(["mark", "--out", "r.json", "--region", "window:Warehouse"]).region == (
        "window:Warehouse"
    )


def test_build_no_longer_demands_a_video():
    args = cli.build_parser().parse_args(["build", "--markers", "m.json", "--out", "o"])
    assert args.video == ""


def test_region_command_prints_the_rectangle(monkeypatch, capsys):
    from whs_recorder.region import Region

    monkeypatch.setattr(cli, "resolve_region", lambda spec: Region(100, 80, 720, 1280, "select"))
    cli.main(["region"])

    assert capsys.readouterr().out.strip() == "100,80,720,1280"


def test_region_command_reports_a_cancelled_selection(monkeypatch):
    monkeypatch.setattr(cli, "resolve_region", lambda spec: None)

    with pytest.raises(SystemExit, match="No region selected"):
        cli.main(["region"])


def test_region_command_can_look_up_a_window(monkeypatch, capsys):
    from whs_recorder.region import Region

    asked = {}

    def fake_resolve(spec):
        asked["spec"] = spec
        return Region(0, 0, 500, 900, "window:Warehouse")

    monkeypatch.setattr(cli, "resolve_region", fake_resolve)
    cli.main(["region", "--window", "Warehouse"])

    assert asked["spec"] == "window:Warehouse"
    assert capsys.readouterr().out.strip() == "0,0,500,900"
