import json

import pytest

from whs_recorder.instructions import EXAMPLE
from whs_recorder.recording import (
    FORMAT,
    FORMAT_VERSION,
    INFO,
    STEP,
    SUBTASK_START,
    InfoStep,
    Recording,
    Step,
    SubtaskEnd,
    SubtaskStart,
)


def sample() -> Recording:
    r = Recording(name="Receive a purchase order line", description="WHS mobile receiving.")
    r.add(SubtaskStart(t=0.2, name="Open the work"))
    r.add(Step(t=1.0, action="menu", control="Inbound"))
    r.add(Step(t=2.0, action="scan", control="LP", value="LP000123"))
    r.add(SubtaskEnd(t=3.0))
    r.add(Step(t=4.0, action="enter", control="Quantity", value="12", title="Count first", note="Ask a lead."))
    r.add(InfoStep(t=5.0, text="Move the pallet to the staging lane"))
    r.add(Step(t=6.0, action="tap", control="OK", is_loading=True))
    return r


def test_outline_numbers_steps_continuously_across_subtasks():
    entries = sample().outline()
    assert [(e.kind, e.number, e.depth) for e in entries] == [
        (SUBTASK_START, None, 0),
        (STEP, 1, 1),
        (STEP, 2, 1),
        (STEP, 3, 0),
        (INFO, 4, 0),
    ]


def test_outline_carries_the_node_index_so_screenshots_can_be_matched():
    entries = sample().outline()
    assert [e.node_index for e in entries] == [0, 1, 2, 4, 5]


def test_loading_steps_are_skipped_and_take_no_number():
    assert [e.number for e in sample().outline(skip_loading=True)][-1] == 4
    numbered = [e for e in sample().outline(skip_loading=False) if e.number]
    assert numbered[-1].number == 5


def test_hidden_steps_are_left_out_of_the_guide():
    r = Recording()
    r.add(Step(t=1.0, action="tap", control="One"))
    r.add(Step(t=2.0, action="tap", control="Two", hidden=True))
    r.add(Step(t=3.0, action="tap", control="Three"))

    assert [e.node.control for e in r.outline()] == ["One", "Three"]
    assert [e.number for e in r.outline()] == [1, 2]
    assert len(r.outline(include_hidden=True)) == 3


def test_a_hidden_subtask_heading_is_left_out_but_its_steps_stay_grouped():
    r = Recording()
    r.add(SubtaskStart(t=0.1, name="Setup", hidden=True))
    r.add(Step(t=1.0, action="tap", control="One"))
    r.add(SubtaskEnd(t=2.0))

    entries = r.outline()
    assert [e.kind for e in entries] == [STEP]
    assert entries[0].depth == 1


def test_nested_subtasks_increase_depth():
    r = Recording()
    r.add(SubtaskStart(t=0.1, name="Outer"))
    r.add(SubtaskStart(t=0.2, name="Inner"))
    r.add(Step(t=1.0, action="tap", control="Deep"))
    r.add(SubtaskEnd(t=2.0))
    r.add(Step(t=3.0, action="tap", control="Shallow"))
    r.add(SubtaskEnd(t=4.0))

    assert [(e.kind, e.depth) for e in r.outline()] == [
        (SUBTASK_START, 0),
        (SUBTASK_START, 1),
        (STEP, 2),
        (STEP, 1),
    ]


def test_open_subtasks_counts_what_is_still_open():
    r = Recording()
    assert r.open_subtasks() == 0
    r.add(SubtaskStart(name="A"))
    r.add(SubtaskStart(name="B"))
    assert r.open_subtasks() == 2
    r.add(SubtaskEnd())
    assert r.open_subtasks() == 1


def test_an_unbalanced_subtask_end_does_not_break_the_outline():
    r = Recording()
    r.add(SubtaskEnd(t=0.1))
    r.add(Step(t=1.0, action="tap", control="One"))
    assert [e.depth for e in r.outline()] == [0]


def test_instructions_follow_the_value_mode():
    entries = sample().outline()
    assert entries[2].node.instruction() == "In the LP field, scan 'LP000123'."
    assert entries[2].node.instruction(EXAMPLE) == "In the LP field, scan the value from the label."


def test_info_step_text_is_used_as_written():
    assert InfoStep(text="Move the pallet").instruction() == "Move the pallet."
    assert InfoStep(text="Move the pallet.").instruction() == "Move the pallet."


def test_round_trip_through_json(tmp_path):
    path = tmp_path / "recording.json"
    sample().save(str(path))

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["format"] == FORMAT
    assert data["version"] == FORMAT_VERSION

    loaded = Recording.load(str(path))
    assert loaded.name == "Receive a purchase order line"
    assert loaded.description == "WHS mobile receiving."
    assert [type(n).__name__ for n in loaded.nodes] == [
        "SubtaskStart", "Step", "Step", "SubtaskEnd", "Step", "InfoStep", "Step",
    ]
    assert loaded.nodes[4].title == "Count first"
    assert loaded.nodes[4].note == "Ask a lead."
    assert [e.number for e in loaded.outline()] == [None, 1, 2, 3, 4]


def test_unknown_node_fields_are_ignored_on_load(tmp_path):
    path = tmp_path / "recording.json"
    path.write_text(
        json.dumps({"nodes": [{"type": "step", "control": "OK", "invented_field": 1}]}), encoding="utf-8"
    )
    assert Recording.load(str(path)).nodes[0].control == "OK"


def test_legacy_markers_file_still_loads(tmp_path):
    """Pre-v0.3 files held the whole sentence in 'title'."""
    path = tmp_path / "step_markers.json"
    path.write_text(
        json.dumps({
            "start_epoch": 12.0,
            "monitor_index": 2,
            "diff_threshold": 9.0,
            "markers": [
                {"t": 1.5, "title": "Scan the licence plate", "notes": "LP on the pallet", "is_loading": False},
                {"t": 2.5, "title": "Loading", "notes": "", "is_loading": True},
            ],
        }),
        encoding="utf-8",
    )

    recording = Recording.load(str(path))

    assert recording.start_epoch == 12.0
    assert recording.monitor_index == 2
    assert len(recording.steps) == 2
    assert recording.steps[0].instruction() == "Scan the licence plate."
    assert recording.steps[0].note == "LP on the pallet"
    assert [e.number for e in recording.outline()] == [1]


def test_empty_recording_has_an_empty_outline():
    assert Recording().outline() == []


def test_a_save_that_fails_leaves_the_previous_recording_intact(tmp_path, monkeypatch):
    """An hour of someone's afternoon should not be lost to a half-written file."""
    import json as json_module

    path = tmp_path / "recording.json"
    sample().save(str(path))
    before = path.read_text(encoding="utf-8")

    def explode(*args, **kwargs):
        raise OSError("the disk filled up")

    monkeypatch.setattr(json_module, "dump", explode)

    with pytest.raises(OSError):
        sample().save(str(path))

    assert path.read_text(encoding="utf-8") == before


def test_saving_leaves_no_temporary_file_behind(tmp_path):
    path = tmp_path / "recording.json"
    sample().save(str(path))

    assert [p.name for p in tmp_path.iterdir()] == ["recording.json"]


def test_a_step_can_be_dropped():
    """Recording without being asked about every click means some steps are
    noise, and the review screen has to be able to throw them away."""
    r = sample()
    before = len(r.nodes)

    dropped = r.remove(1)

    assert dropped.control == "Inbound"
    assert len(r.nodes) == before - 1
    assert [e.number for e in r.outline()] == [None, 1, 2, 3]


def test_dropping_something_that_is_not_there_changes_nothing():
    r = sample()
    before = list(r.nodes)

    assert r.remove(99) is None
    assert r.remove(-5) is None
    assert r.nodes == before


def test_a_step_can_be_moved():
    r = Recording()
    for name in ("one", "two", "three"):
        r.add(Step(action="tap", control=name))

    assert r.move(2, -1) == 1
    assert [n.control for n in r.nodes] == ["one", "three", "two"]

    assert r.move(0, 1) == 1
    assert [n.control for n in r.nodes] == ["three", "one", "two"]


def test_moving_past_either_end_stops_at_the_end():
    r = Recording()
    for name in ("one", "two"):
        r.add(Step(action="tap", control=name))

    assert r.move(0, -3) == 0
    assert r.move(1, 9) == 1
    assert [n.control for n in r.nodes] == ["one", "two"]
