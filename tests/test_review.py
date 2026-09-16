"""The review window: the list it shows, and the editing it does.

The list text is pure and is exercised directly. The window itself needs a
display, so those tests skip where there is none - which on the CI that matters,
Windows, there always is.
"""

import os

import numpy as np
import pytest

from conftest import open_window

from whs_recorder.recording import InfoStep, Recording, Step, SubtaskEnd, SubtaskStart
from whs_recorder.review import Review, describe, lines
from whs_recorder.utils import write_image


def sample() -> Recording:
    r = Recording(name="Receive a purchase order line", description="WHS mobile receiving.")
    r.add(SubtaskStart(t=0.1, name="Open the work"))
    r.add(Step(t=1.0, action="menu", control="Inbound", screen="Main menu"))
    r.add(SubtaskEnd(t=1.5))
    r.add(InfoStep(t=2.0, text="Collect the paper list from the printer"))
    r.add(Step(t=3.0, action="scan", control="LP", value="LP000123", screen="Purchase receive"))
    r.add(Step(t=4.0, action="tap", control="OK", is_loading=True))
    return r


@pytest.fixture
def recording_path(tmp_path):
    path = tmp_path / "recording.json"
    sample().save(str(path))
    return str(path)


@pytest.fixture
def window(recording_path):
    """A real review window, or a skip where no display is available."""
    review = open_window(lambda: Review(recording_path))
    yield review
    try:
        review.root.destroy()
    except Exception:
        pass


# ------------------------------------------------------------------- the list


def test_a_step_reads_as_the_sentence_it_will_produce():
    step = Step(action="scan", control="LP", value="LP000123")

    assert describe(step, 4) == "  4. In the LP field, scan 'LP000123'."


def test_a_section_heading_is_shown_as_one():
    assert describe(SubtaskStart(name="Open the work"), None) == "     [ Open the work ]"
    assert describe(SubtaskStart(), None) == "     [ Section ]"


def test_an_empty_note_says_so_rather_than_showing_a_blank_line():
    assert "(empty note)" in describe(InfoStep(), 2)


def test_numbering_matches_the_document_and_skips_what_is_left_out():
    shown = lines(sample())

    assert shown[0] == "     [ Open the work ]"
    assert shown[1].startswith("  1. Tap Inbound.")
    assert shown[2] == "     [ end of section ]"
    assert shown[3].startswith("  2. Collect the paper list")
    assert shown[4].startswith("  3. In the LP field, scan")
    # The loading step keeps its place but takes no number, so the numbers in
    # the list are the numbers the reader will see.
    assert shown[5].startswith("     Tap OK.")
    assert shown[5].endswith("- left out")


def test_a_hidden_step_is_marked_and_unnumbered():
    r = Recording()
    r.add(Step(action="tap", control="Inbound", hidden=True))
    r.add(Step(action="tap", control="OK"))

    assert lines(r) == ["     Tap Inbound.   - left out", "  1. Tap OK."]


# ----------------------------------------------------------------- the window


def test_the_window_lists_every_node(window):
    assert window.listbox.size() == len(window.recording.nodes)
    assert window.selected == 0


def test_picking_a_step_fills_the_boxes_from_it(window):
    window._show(4)

    assert window.action.get() == "Scan a value"
    assert window.fields["control"].get() == "LP"
    assert window.fields["value"].get() == "LP000123"
    assert window.fields["screen"].get() == "Purchase receive"
    assert window.skip.get() is False


def test_an_edit_is_kept_when_another_step_is_picked(window):
    window._show(4)
    window.fields["control"].set("Licence plate")
    window.fields["note"].set("Scan the label on the pallet.")

    window.listbox.selection_clear(0, "end")
    window.listbox.selection_set(1)
    window._on_pick()

    step = window.recording.nodes[4]
    assert step.control == "Licence plate"
    assert step.note == "Scan the label on the pallet."
    assert window.selected == 1


def test_changing_the_action_rewrites_the_sentence(window):
    window._show(1)
    window.action.set("Select a row in a list")
    window._commit()

    assert window.recording.nodes[1].action == "select"
    assert lines(window.recording)[1].endswith("In the list, select Inbound.")


def test_keeping_a_step_the_recorder_thought_was_loading_really_keeps_it(window):
    window._show(5)
    assert window.skip.get() is True  # flagged by the recorder

    window.skip.set(False)
    window._commit()

    step = window.recording.nodes[5]
    assert step.hidden is False
    # --skip-loading must not drop it after being told to keep it.
    assert step.is_loading is False
    assert [e.node for e in window.recording.outline(skip_loading=True)][-1] is step


def test_leaving_a_step_out_takes_it_out_of_the_document(window):
    window._show(1)
    window.skip.set(True)
    window._commit()

    assert window.recording.nodes[1].hidden is True
    assert all(e.node is not window.recording.nodes[1] for e in window.recording.outline())


def test_a_section_heading_edits_its_name_not_a_step_field(window):
    window._show(0)

    assert window.labels["title"].cget("text") == "Name of this section"
    assert window.fields["title"].get() == "Open the work"
    assert str(window.action_box.cget("state")) == "disabled"
    assert str(window.entries["control"].cget("state")) == "disabled"

    window.fields["title"].set("Sign in")
    window._commit()
    assert window.recording.nodes[0].name == "Sign in"


def test_an_info_step_edits_its_text(window):
    window._show(3)

    assert window.fields["title"].get() == "Collect the paper list from the printer"

    window.fields["title"].set("Collect the picking list")
    window._commit()
    assert window.recording.nodes[3].text == "Collect the picking list"


def test_the_end_of_a_section_has_nothing_to_edit(window):
    window._show(2)

    assert str(window.entries["title"].cget("state")) == "disabled"
    assert str(window.skip_box.cget("state")) == "disabled"


def test_moving_a_step_moves_it_in_the_list_too(window):
    window._show(4)
    moved = window.recording.nodes[4]
    window._move(-1)

    assert window.recording.nodes[3] is moved
    assert window.selected == 3
    assert window.listbox.curselection() == (3,)


def test_a_step_at_the_top_cannot_be_moved_off_the_end(window):
    window._show(0)
    window._move(-1)

    assert window.selected == 0
    assert window.listbox.size() == len(window.recording.nodes)


def test_deleting_a_step_removes_it_and_keeps_a_selection(window):
    window._show(1)
    before = len(window.recording.nodes)
    window._delete()

    assert len(window.recording.nodes) == before - 1
    assert window.selected == 1
    assert window.listbox.size() == before - 1


def test_deleting_the_bottom_step_selects_the_one_above_it(window):
    last = len(window.recording.nodes) - 1
    window._show(last)
    window._delete()

    assert window.selected == last - 1
    assert window.listbox.curselection() == (last - 1,)
    # and the boxes show that step, not the one that is gone
    assert window.fields["control"].get() == window.recording.nodes[last - 1].control


def test_deleting_the_last_one_leaves_an_empty_list_rather_than_an_error(window):
    while window.recording.nodes:
        window.selected = 0
        window._delete()

    assert window.listbox.size() == 0
    assert window.selected == -1


def test_saving_writes_the_edits_to_the_file(window, recording_path):
    window._show(4)
    window.fields["value"].set("LP000999")
    window.save()

    reloaded = Recording.load(recording_path)
    assert reloaded.nodes[4].value == "LP000999"
    assert window.dirty is False


def test_an_untouched_recording_is_not_reported_as_changed(window):
    window._show(4)
    window._show(1)
    window._commit()

    assert window.dirty is False


def test_building_hands_the_saved_path_over(recording_path):
    built = []
    review = open_window(lambda: Review(recording_path, on_build=built.append))
    review._show(4)
    review.fields["control"].set("Licence plate")
    review._save_and_build()

    assert built == [recording_path]
    assert Recording.load(recording_path).nodes[4].control == "Licence plate"


# ------------------------------------------------------------ the screenshots


def test_the_screenshot_of_the_picked_step_is_shown(tmp_path):
    shot = tmp_path / "shots" / "step1.png"
    write_image(str(shot), np.full((640, 360, 3), 200, dtype=np.uint8))

    r = Recording(name="With a picture")
    r.add(Step(action="tap", control="OK", action_img=os.path.join("shots", "step1.png")))
    path = tmp_path / "recording.json"
    r.save(str(path))

    review = open_window(lambda: Review(str(path)))
    try:
        assert review.photo is not None
        # Scaled down to fit the column rather than shown at full size.
        assert review.photo.height() <= 500
        assert review.preview.cget("text") == ""
    finally:
        review.root.destroy()


def test_a_missing_screenshot_says_so_instead_of_failing(window):
    window.recording.nodes[1].action_img = "shots/gone.png"
    window._show(1)

    assert window.preview.cget("text") == "No screenshot for this step"
    assert window.photo is None


def test_a_step_without_a_screenshot_does_not_keep_showing_the_last_one(tmp_path):
    shot = tmp_path / "shots" / "step1.png"
    write_image(str(shot), np.full((640, 360, 3), 200, dtype=np.uint8))

    r = Recording(name="One picture between two steps")
    r.add(Step(action="tap", control="Inbound", action_img=os.path.join("shots", "step1.png")))
    r.add(Step(action="tap", control="OK"))
    path = tmp_path / "recording.json"
    r.save(str(path))

    review = open_window(lambda: Review(str(path)))
    try:
        assert review.photo is not None
        review._show(1)
        assert review.photo is None
        assert str(review.preview.cget("image")) == ""
    finally:
        review.root.destroy()


def test_an_unreadable_screenshot_is_reported_rather_than_closing_the_window(window, tmp_path):
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"not a picture")
    window.recording.nodes[1].action_img = str(broken)

    window._show(1)

    assert "Cannot show the screenshot" in window.preview.cget("text")
    assert window.photo is None
