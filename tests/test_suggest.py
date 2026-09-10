import numpy as np
import pytest

from whs_recorder.ocr import TextLine
from whs_recorder.suggest import (
    Suggestion,
    clean,
    control_at,
    screen_title,
    suggest_step,
    value_appeared,
)


def line(text, left, top, width=120, height=18):
    return TextLine(text=text, left=left, top=top, width=width, height=height, confidence=90.0)


#: A handheld screen: a title bar, two labelled fields and a button.
SCREEN = [
    line("Purchase receive", 16, 18, width=200, height=26),
    line("Purchase order", 20, 100, height=14),
    line("PO000045", 32, 124),
    line("Quantity", 20, 190, height=14),
    line("12", 32, 214),
    line("OK", 60, 510, width=60, height=22),
]


def reader(frames):
    """Return prepared lines per frame, keyed by the frame's first pixel."""
    def read(frame):
        return frames[int(frame[0, 0, 0])]
    return read


def frame(marker, height=640, width=360):
    img = np.zeros((height, width, 3), dtype=np.uint8)
    img[0, 0, 0] = marker
    return img


def test_the_title_bar_names_the_screen():
    assert screen_title(SCREEN, height=640) == "Purchase receive"


def test_text_below_the_title_band_is_not_the_screen_name():
    assert screen_title([line("Quantity", 20, 400)], height=640) == ""


def test_the_biggest_line_in_the_band_wins():
    lines = [line("EDB", 300, 20, width=40, height=12), line("Purchase receive", 16, 18, height=26)]
    assert screen_title(lines, height=640) == "Purchase receive"


def test_a_tap_on_a_button_takes_the_button_label():
    assert control_at(SCREEN, (75, 520)) == "OK"


def test_a_tap_in_a_field_takes_the_label_above_it():
    assert control_at(SCREEN, (150, 218)) == "Quantity"


def test_the_screen_name_is_never_offered_as_the_control():
    assert control_at(SCREEN, (100, 24), skip="Purchase receive") != "Purchase receive"


def test_a_tap_on_empty_space_suggests_nothing():
    assert control_at(SCREEN, (350, 620)) == ""


def test_no_tap_means_no_control():
    """A step recorded from the Enter key has no position to read."""
    assert control_at(SCREEN, None) == ""


def test_the_value_is_the_text_that_was_not_there_before():
    before = [l for l in SCREEN if l.text != "PO000045"]
    assert value_appeared(before, SCREEN, point=(150, 128)) == "PO000045"


def test_a_screen_that_did_not_change_offers_no_value():
    assert value_appeared(SCREEN, SCREEN) == ""


def test_the_screen_and_control_are_not_offered_as_the_value():
    before = []
    assert value_appeared(before, SCREEN, point=(150, 128), skip=("Purchase receive", "Quantity")) not in (
        "Purchase receive", "Quantity",
    )


def test_the_nearest_new_text_to_the_tap_wins():
    before = [l for l in SCREEN if l.text not in ("PO000045", "12")]
    assert value_appeared(before, SCREEN, point=(150, 218)) == "12"


@pytest.mark.parametrize(
    "raw,expected",
    [("  Purchase   receive  ", "Purchase receive"), ("Quantity:", "Quantity"), ("", "")],
)
def test_cleaning_ocr_text(raw, expected):
    assert clean(raw) == expected


def test_suggest_step_reads_a_whole_step_off_the_screen():
    before = [l for l in SCREEN if l.text != "PO000045"]
    read = reader({1: SCREEN, 2: before})

    found = suggest_step(frame(1), point=(150, 128), before=frame(2), reader=read)

    assert found.screen == "Purchase receive"
    assert found.control == "Purchase order"
    assert found.value == "PO000045"


def test_suggest_step_without_a_previous_frame_offers_no_value():
    read = reader({1: SCREEN})

    found = suggest_step(frame(1), point=(75, 520), reader=read)

    assert found.screen == "Purchase receive"
    assert found.control == "OK"
    assert found.value == ""


def test_suggest_step_is_empty_without_ocr():
    found = suggest_step(frame(1), point=(75, 520), reader=lambda f: [])

    assert found.is_empty()
    assert found == Suggestion()


def test_suggest_step_is_empty_without_a_frame():
    assert suggest_step(None, reader=lambda f: []).is_empty()


def test_a_tap_far_to_the_side_of_a_label_is_not_that_control():
    """Dropping the horizontal test entirely made empty space claim the nearest label."""
    assert control_at(SCREEN, (350, 620)) == ""


def test_a_tap_across_a_wide_input_still_finds_its_short_label():
    """The label is short and left-aligned; the box it names spans the screen."""
    assert control_at(SCREEN, (300, 218)) == "Quantity"


def test_a_result_banner_is_not_offered_as_the_value():
    """Plenty changes when an action lands; only text near the tap is the value."""
    banner = line("Work completed 1", 0, 600, width=360, height=18)
    before = [l for l in SCREEN if l.text != "12"]

    assert value_appeared(before, SCREEN + [banner], point=(97, 520)) == ""
    assert value_appeared(before, SCREEN + [banner], point=(150, 218)) == "12"
