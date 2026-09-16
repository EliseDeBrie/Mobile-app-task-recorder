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
