import io
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
    r.add(Step(t=1.5, action="scan", control="LP", value="LP000123", screen="Purchase receive",
               title="Check the label", note="Reprint a damaged label."))
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
    assert "On the Purchase receive screen:" in out
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


def test_an_expected_failure_is_a_plain_message_not_a_stack_trace(monkeypatch):
    """A consultant on a customer machine should read what went wrong."""
    def refuse(**kwargs):
        raise RuntimeError("Cannot open video: run.mp4")

    monkeypatch.setattr(cli, "build_evidence", refuse)

    with pytest.raises(SystemExit) as exit_info:
        cli.main(["build", "--markers", "m.json", "--out", "o", "--video", "run.mp4"])

    assert "Error: Cannot open video: run.mp4" in str(exit_info.value)


def test_a_bad_value_is_reported_the_same_way(monkeypatch):
    def refuse(**kwargs):
        raise ValueError("Unknown value mode 'loud'")

    monkeypatch.setattr(cli, "build_evidence", refuse)

    with pytest.raises(SystemExit, match="Unknown value mode"):
        cli.main(["build", "--markers", "m.json", "--out", "o"])


def test_an_unexpected_failure_still_surfaces_as_itself(monkeypatch):
    """A real defect must not be flattened into a tidy message."""
    def explode(**kwargs):
        raise ZeroDivisionError("division by zero")

    monkeypatch.setattr(cli, "build_evidence", explode)

    with pytest.raises(ZeroDivisionError):
        cli.main(["build", "--markers", "m.json", "--out", "o"])


def test_the_version_is_reported(capsys):
    from whs_recorder import __version__

    with pytest.raises(SystemExit):
        cli.main(["--version"])

    assert __version__ in capsys.readouterr().out


def test_no_arguments_at_all_opens_the_launcher(monkeypatch):
    """What double-clicking the program does. A console usage message there
    would be shouting at a window nobody opened."""
    import whs_recorder.app as app

    opened = []
    monkeypatch.setattr(app, "main", lambda: opened.append(True))
    monkeypatch.setattr(cli.sys, "argv", ["whs-recorder"])

    assert cli.main() is None
    assert opened == [True]


def test_an_explicit_empty_argument_list_still_shows_usage(monkeypatch):
    """Called as a library with no command, argparse should still complain."""
    monkeypatch.setattr(cli.sys, "argv", ["whs-recorder"])

    with pytest.raises(SystemExit):
        cli.main([])


def test_a_command_given_on_the_command_line_does_not_open_a_window(monkeypatch):
    import whs_recorder.app as app

    monkeypatch.setattr(app, "main", lambda: pytest.fail("should not open the launcher"))
    monkeypatch.setattr(cli.sys, "argv", ["whs-recorder", "check"])

    cli.main(["check"])


def test_a_working_stream_is_never_taken_over(monkeypatch):
    """The launcher runs these commands as children and hands them pipes.
    Rebinding those to a console would send their output to a window instead of
    to the log pane."""
    import whs_recorder.app as app

    monkeypatch.setattr(app.os, "name", "nt")
    monkeypatch.setattr(app.sys, "frozen", True, raising=False)

    attached = []
    monkeypatch.setattr(app, "borrow_parent_console", app.borrow_parent_console)

    stdout_before = app.sys.stdout
    app.borrow_parent_console()

    assert app.sys.stdout is stdout_before
    assert attached == []


def test_nothing_is_borrowed_from_a_checkout(monkeypatch):
    """Unpackaged, Python already gave us usable streams."""
    import whs_recorder.app as app

    monkeypatch.setattr(app.os, "name", "nt")
    monkeypatch.setattr(app.sys, "frozen", False, raising=False)

    stdout_before = app.sys.stdout
    app.borrow_parent_console()

    assert app.sys.stdout is stdout_before


def test_nothing_is_borrowed_away_from_windows(monkeypatch):
    import whs_recorder.app as app

    monkeypatch.setattr(app.os, "name", "posix")
    monkeypatch.setattr(app.sys, "frozen", True, raising=False)

    stdout_before = app.sys.stdout
    app.borrow_parent_console()

    assert app.sys.stdout is stdout_before


class _FakeKernel:
    def __init__(self, attaches: bool):
        self.attaches = attaches
        self.calls = []

    def AttachConsole(self, which):  # noqa: N802 - the Windows API spells it this way
        self.calls.append(which)
        return 1 if self.attaches else 0


def _fake_ctypes(monkeypatch, attaches: bool):
    import types as _types

    kernel = _FakeKernel(attaches)
    fake = _types.ModuleType("ctypes")
    fake.windll = _types.SimpleNamespace(kernel32=kernel)
    monkeypatch.setitem(cli.sys.modules, "ctypes", fake)
    return kernel


def _fake_console_open(monkeypatch):
    """Stand in for opening the console device, which does not exist here."""
    import builtins

    opened = []
    real_open = builtins.open

    def fake_open(name, *args, **kwargs):
        if name == "CONOUT$":
            opened.append(name)
            return io.StringIO()
        return real_open(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", fake_open)
    return opened


def test_a_command_started_from_a_terminal_prints_into_it(monkeypatch):
    """Windowed programs have nowhere to print, which would leave the command
    line mute. Started from a terminal it borrows that terminal's console."""
    import whs_recorder.app as app

    monkeypatch.setattr(app.os, "name", "nt")
    monkeypatch.setattr(app.sys, "frozen", True, raising=False)
    monkeypatch.setattr(app.sys, "stdout", None)
    monkeypatch.setattr(app.sys, "stderr", None)
    kernel = _fake_ctypes(monkeypatch, attaches=True)
    opened = _fake_console_open(monkeypatch)

    app.borrow_parent_console()

    assert kernel.calls == [-1]  # ATTACH_PARENT_PROCESS
    assert opened == ["CONOUT$", "CONOUT$"]
    assert app.sys.stdout is not None and app.sys.stderr is not None


def test_started_from_explorer_there_is_no_terminal_to_borrow(monkeypatch):
    """Double-clicked, there is no parent console and nothing should be opened."""
    import whs_recorder.app as app

    monkeypatch.setattr(app.os, "name", "nt")
    monkeypatch.setattr(app.sys, "frozen", True, raising=False)
    monkeypatch.setattr(app.sys, "stdout", None)
    monkeypatch.setattr(app.sys, "stderr", None)
    kernel = _fake_ctypes(monkeypatch, attaches=False)
    opened = _fake_console_open(monkeypatch)

    app.borrow_parent_console()

    assert kernel.calls == [-1]
    assert opened == []
    assert app.sys.stdout is None


def test_mark_records_without_asking_unless_it_is_told_to(monkeypatch):
    parser = cli.build_parser()
    assert parser.parse_args(["mark", "--out", "r.json"]).ask_each_step is False
    assert parser.parse_args(["mark", "--out", "r.json", "--ask-each-step"]).ask_each_step is True


def test_mark_passes_ask_each_step_to_the_recorder(monkeypatch):
    seen = {}

    def fake_recorder(**kwargs):
        seen.update(kwargs)

    monkeypatch.setitem(
        __import__("sys").modules, "whs_recorder.marker_recorder",
        type("M", (), {"run_marker_recorder": staticmethod(fake_recorder)}),
    )

    cli.main(["mark", "--out", "r.json", "--region", "full", "--ask-each-step"])

    assert seen["ask_each_step"] is True
    assert seen["out_path"] == "r.json"


def test_review_opens_the_recording_it_is_given(monkeypatch, recording_path):
    opened = []
    monkeypatch.setitem(
        __import__("sys").modules, "whs_recorder.review",
        type("M", (), {"main": staticmethod(opened.append)}),
    )

    cli.main(["review", "--markers", recording_path])

    assert opened == [recording_path]


def test_review_needs_a_recording():
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["review"])
