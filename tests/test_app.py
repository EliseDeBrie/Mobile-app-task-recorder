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
    runs = _capture_runs(launcher)
    launcher.name.set("Receive a purchase order line")
    launcher.folder.set(str(tmp_path))

    launcher._record()

    assert runs[0]["args"][0] == "mark"
    # However the recorder ends, what it saved is looked at.
    assert runs[0]["on_finish"] is not None
    assert runs[0]["on_success"] is None


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


def _capture_runs(launcher):
    """Stand in for _run, keeping what it was asked to do."""
    runs = []

    def fake_run(args, done, on_success=None, on_finish=None):
        runs.append({"args": args, "done": done, "on_success": on_success, "on_finish": on_finish})

    launcher._run = fake_run
    return runs


def test_the_document_sits_beside_the_recording_with_the_same_name():
    from whs_recorder.app import build_folder_for, document_for

    assert document_for(r"C:\rec\Solina inbound.json") == r"C:\rec\Solina inbound.docx"
    assert build_folder_for(r"C:\rec\Solina inbound.json") == r"C:\rec\Solina inbound_build"


def test_a_finished_recording_is_built_and_opened_for_checking(launcher, recording_path):
    runs = _capture_runs(launcher)

    launcher._after_recording(recording_path, exit_code=0)

    build = runs[0]["args"]
    assert build[0] == "build"
    assert build[build.index("--document") + 1].endswith(".docx")
    assert launcher._review_open() is True
    launcher.reviewing.root.destroy()


def test_a_recorder_that_crashed_after_saving_does_not_cost_the_document(launcher, recording_path):
    """It saves before anything else on the way out, and it has crashed there."""
    runs = _capture_runs(launcher)

    launcher._after_recording(recording_path, exit_code=1)

    assert runs and runs[0]["args"][0] == "build"
    assert "was saved" in log_of(launcher)
    launcher.reviewing.root.destroy()


def test_no_recording_means_nothing_to_build(launcher, tmp_path):
    runs = _capture_runs(launcher)

    launcher._after_recording(str(tmp_path / "nothing.json"), exit_code=1)

    assert runs == []
    assert "nothing to build" in log_of(launcher)


def test_saving_the_steps_remakes_the_document_quietly(launcher, recording_path):
    runs = _capture_runs(launcher)

    launcher._steps_saved(recording_path)

    assert runs[0]["args"][0] == "build"
    assert runs[0]["on_success"] is None  # not opened: the window is still up


def test_done_makes_the_document_and_opens_it(launcher, recording_path, monkeypatch):
    runs = _capture_runs(launcher)
    opened = []
    monkeypatch.setattr(launcher, "_open_path", opened.append)

    launcher._steps_done(recording_path)
    runs[0]["on_success"]()

    assert opened == [os.path.splitext(recording_path)[0] + ".docx"]


def test_the_build_button_builds_the_chosen_recording_and_opens_it(launcher, recording_path, monkeypatch):
    runs = _capture_runs(launcher)
    opened = []
    monkeypatch.setattr(launcher, "_open_path", opened.append)
    launcher.recording_file.set(recording_path)

    launcher._build()
    runs[0]["on_success"]()

    args = runs[0]["args"]
    assert args[args.index("--markers") + 1] == recording_path
    assert opened and opened[0].endswith(".docx")


def test_commands_run_one_after_another_not_at_once(launcher, monkeypatch):
    """Two builds writing the same document at the same time would corrupt it."""
    started = []

    class FakeProcess:
        stdout = iter([])
        returncode = 0

        def wait(self):
            pass

    def fake_popen(cmd, **kwargs):
        started.append(cmd[-1])
        return FakeProcess()

    monkeypatch.setattr("subprocess.Popen", fake_popen)

    import threading

    def settle():
        for thread in threading.enumerate():
            if thread is not threading.current_thread() and thread.daemon:
                thread.join(timeout=2)
        launcher._drain()

    launcher._run(["check", "first"], "one")
    launcher._run(["check", "second"], "two")
    assert started == ["first"]        # the second waits its turn
    assert len(launcher.waiting) == 1

    settle()                           # the first finishes; the second starts
    assert started == ["first", "second"]

    settle()                           # and the second finishes, inside this test
    assert launcher.active is False
    assert launcher.job is None


def test_the_worker_thread_never_holds_the_window(launcher, monkeypatch):
    """A thread that holds the window can be the last to let go of it, and Tk
    aborts the process when a window is finalised off its own thread."""
    import threading

    targets = []

    class NoThread:
        def __init__(self, target, daemon=False):
            targets.append(target)

        def start(self):
            pass

    monkeypatch.setattr(threading, "Thread", NoThread)

    launcher._run(["check"], "done", on_success=lambda: None)

    worker = targets[0]
    held = [cell.cell_contents for cell in worker.__closure__]
    assert launcher not in held
    assert not any(getattr(item, "__self__", None) is launcher for item in held)
    assert launcher.messages in held and launcher.calls in held


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
    assert launcher.running is None


def test_the_document_goes_where_the_person_said(launcher, recording_path):
    runs = _capture_runs(launcher)
    launcher.document_file.set(r"C:\\Customers\\Solina\\Inbound guide.docx")

    launcher._build_document(recording_path)

    args = runs[0]["args"]
    assert args[args.index("--document") + 1] == r"C:\\Customers\\Solina\\Inbound guide.docx"


def test_a_document_name_without_the_extension_gets_it(launcher, recording_path):
    launcher.document_file.set("Inbound guide")

    assert launcher.document_path(recording_path) == "Inbound guide.docx"


def test_an_empty_document_box_means_beside_the_recording(launcher, recording_path):
    from whs_recorder.app import document_for

    launcher.document_file.set("   ")

    assert launcher.document_path(recording_path) == document_for(recording_path)


def test_starting_a_recording_fills_the_document_box_in(launcher, tmp_path):
    _capture_runs(launcher)
    launcher.name.set("Receive a purchase order line")
    launcher.folder.set(str(tmp_path))

    launcher._record()

    assert launcher.document_file.get() == os.path.join(
        str(tmp_path), "Receive a purchase order line.docx"
    )


def test_a_document_place_chosen_beforehand_is_kept_when_recording_starts(launcher, tmp_path):
    _capture_runs(launcher)
    launcher.name.set("Receive a purchase order line")
    launcher.folder.set(str(tmp_path))
    launcher.document_file.set(str(tmp_path / "elsewhere" / "Guide.docx"))

    launcher._record()

    assert launcher.document_file.get() == str(tmp_path / "elsewhere" / "Guide.docx")


def test_browsing_to_an_older_recording_points_the_document_beside_it(launcher, recording_path, monkeypatch):
    from tkinter import filedialog

    monkeypatch.setattr(filedialog, "askopenfilename", lambda **k: recording_path)

    launcher._pick_recording()

    assert launcher.document_file.get() == os.path.splitext(recording_path)[0] + ".docx"
