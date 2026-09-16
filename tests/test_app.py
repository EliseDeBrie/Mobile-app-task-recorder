"""The launcher window: the parts that decide what happens, not the layout."""

import os

import pytest

from conftest import open_window

from whs_recorder.app import Launcher, command_environment, command_prefix
from whs_recorder.recording import Recording, Step


@pytest.fixture
def recording_path(tmp_path):
    r = Recording(name="Receive a purchase order line")
    r.add(Step(action="tap", control="Inbound"))
    path = tmp_path / "recording.json"
    r.save(str(path))
    return str(path)


@pytest.fixture
def launcher():
    app = open_window(Launcher)
    yield app
    try:
        app.root.destroy()
    except Exception:
        pass


def log_of(app) -> str:
    return app.log.get("1.0", "end")


def test_recording_hands_the_steps_over_to_be_checked(launcher, recording_path, tmp_path):
    started = {}
    launcher._run = lambda args, done, on_success=None: started.update(
        args=args, done=done, on_success=on_success
    )
    launcher.name.set("Receive a purchase order line")
    launcher.folder.set(str(tmp_path))

    launcher._record()

    assert started["args"][0] == "mark"
    assert started["on_success"] is not None


def test_checking_the_steps_opens_one_window_not_two(launcher, recording_path):
    launcher.recording_file.set(recording_path)

    launcher._review_chosen()
    first = launcher.reviewing
    assert first is not None

    launcher._review_chosen()
    assert launcher.reviewing is first
    assert "already open" in log_of(launcher)

    first.root.destroy()


def test_a_closed_review_window_can_be_opened_again(launcher, recording_path):
    launcher.recording_file.set(recording_path)

    launcher._review_chosen()
    launcher.reviewing.root.destroy()

    launcher._review_chosen()
    assert launcher._review_open() is True
    launcher.reviewing.root.destroy()


def test_checking_a_recording_that_is_not_there_says_so(launcher, tmp_path):
    launcher.recording_file.set(str(tmp_path / "nothing.json"))

    launcher._review_chosen()

    assert launcher.reviewing is None
    assert "No recording at" in log_of(launcher)


def test_building_from_the_review_window_uses_that_recording(launcher, recording_path):
    started = {}
    launcher._run = lambda args, done, on_success=None: started.update(args=args)

    launcher._build_from(recording_path)

    assert launcher.recording_file.get() == recording_path
    assert "--markers" in started["args"]
    assert started["args"][started["args"].index("--markers") + 1] == recording_path


def test_the_command_it_runs_can_find_this_package(monkeypatch):
    monkeypatch.delattr("sys.frozen", raising=False)

    assert command_prefix()[1:] == ["-m", "whs_recorder.cli"]

    package_parent = command_environment()["PYTHONPATH"].split(os.pathsep)[0]
    assert os.path.isdir(os.path.join(package_parent, "whs_recorder"))


def test_output_is_line_buffered_so_the_log_pane_is_live(monkeypatch, tmp_path):
    """A pipe is block buffered by default, and the recorder's lines would all
    arrive together when it ended."""
    import io
    import sys

    from whs_recorder.app import print_as_it_happens

    pipe = io.TextIOWrapper(io.BytesIO(), line_buffering=False)
    monkeypatch.setattr(sys, "stdout", pipe)
    monkeypatch.setattr(sys, "stderr", io.TextIOWrapper(io.BytesIO()))

    print_as_it_happens()

    assert pipe.line_buffering is True


def test_a_stream_that_cannot_be_reconfigured_is_left_alone(monkeypatch):
    import sys

    from whs_recorder.app import print_as_it_happens

    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", object())

    print_as_it_happens()  # must not raise


def test_the_worker_hands_window_work_to_the_window_thread(launcher, monkeypatch):
    """Nothing from the worker touches Tk directly; it goes through the queue
    that the window drains itself."""
    import threading

    ran = []
    fake = type("P", (), {})()
    fake.stdout = iter(["one line\n"])
    fake.returncode = 0
    fake.wait = lambda: None
    monkeypatch.setattr("subprocess.Popen", lambda *a, **k: fake)

    launcher._run(["check"], "done", on_success=lambda: ran.append("success"))
    for thread in threading.enumerate():
        if thread is not threading.current_thread() and thread.daemon:
            thread.join(timeout=2)

    assert ran == []  # not yet: it waits for the window's own thread
    launcher._drain()
    assert ran == ["success"]
    assert "one line" in log_of(launcher)
    assert str(launcher.record_button.cget("state")) == "normal"
