import json

import cv2
import numpy as np
import pytest

from conftest import make_screen

from whs_recorder import cli


def test_build_defaults():
    args = cli.build_parser().parse_args(["build", "--video", "v.mp4", "--markers", "m.json", "--out", "o"])

    assert args.result_window == 2.5
    assert args.no_toast is False
    assert args.redact is None
    assert args.result_offsets == "0.6,1.2"


def test_build_passes_the_new_options_through(monkeypatch, tmp_path):
    config = tmp_path / "r.json"
    config.write_text(json.dumps({"regions": [{"name": "r", "box": [0, 0, 1, 0.1]}]}), encoding="utf-8")

    captured = {}
    monkeypatch.setattr(cli, "build_evidence", lambda **kwargs: captured.update(kwargs))

    cli.main([
        "build", "--video", "v.mp4", "--markers", "m.json", "--out", "o",
        "--redact", str(config), "--result-window", "4", "--no-toast", "--skip-loading",
    ])

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
