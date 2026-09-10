import os

import numpy as np
import pytest

from conftest import make_screen

from whs_recorder.utils import (
    edge_density,
    ensure_dir,
    ensure_parent_dir,
    mean_abs_diff,
    quality_score,
    sharpness,
)


def test_ensure_parent_dir_accepts_a_bare_filename(tmp_path, monkeypatch):
    """`--out step_markers.json` used to crash: dirname('x.json') is empty."""
    monkeypatch.chdir(tmp_path)
    ensure_parent_dir("step_markers.json")
    open("step_markers.json", "w", encoding="utf-8").close()
    assert os.path.exists("step_markers.json")


def test_ensure_parent_dir_creates_nested_folders(tmp_path):
    target = tmp_path / "runs" / "today" / "markers.json"
    ensure_parent_dir(str(target))
    assert target.parent.is_dir()


def test_ensure_dir_ignores_an_empty_path():
    ensure_dir("")  # must not raise


def test_sharpness_drops_on_a_blurred_frame():
    screen = make_screen()
    import cv2

    blurred = cv2.GaussianBlur(screen, (21, 21), 0)
    assert sharpness(blurred) < sharpness(screen)


def test_edge_density_is_zero_on_a_blank_frame():
    assert edge_density(np.full((100, 100, 3), 200, dtype=np.uint8)) == 0.0


def test_quality_score_prefers_the_richer_frame():
    blank = np.full((640, 360, 3), 235, dtype=np.uint8)
    assert quality_score(make_screen()) > quality_score(blank)


def test_mean_abs_diff_is_zero_for_identical_frames():
    screen = make_screen()
    assert mean_abs_diff(screen, screen) == 0.0
    assert mean_abs_diff(screen, np.zeros_like(screen)) > 0


class FakeKey:
    """Stands in for a pynput key object."""

    def __init__(self, char=None, vk=None):
        if char is not None:
            self.char = char
        if vk is not None:
            self.vk = vk


def test_is_letter_key_matches_a_plain_letter():
    from whs_recorder.utils import is_letter_key

    assert is_letter_key(FakeKey(char="s"), "s")
    assert is_letter_key(FakeKey(char="S"), "s")
    assert not is_letter_key(FakeKey(char="e"), "s")


def test_is_letter_key_matches_the_control_character():
    """Ctrl+S arrives as \\x13 on some platforms."""
    from whs_recorder.utils import is_letter_key

    assert is_letter_key(FakeKey(char="\x13"), "s")
    assert is_letter_key(FakeKey(char="\x05"), "e")
    assert not is_letter_key(FakeKey(char="\x13"), "e")


def test_is_letter_key_matches_the_virtual_key_code():
    from whs_recorder.utils import is_letter_key

    assert is_letter_key(FakeKey(vk=ord("S")), "s")
    assert not is_letter_key(FakeKey(vk=ord("E")), "s")


def test_is_letter_key_ignores_a_key_with_neither():
    from whs_recorder.utils import is_letter_key

    assert not is_letter_key(FakeKey(), "s")


def test_an_image_survives_a_path_with_accents(tmp_path):
    """cv2.imread and imwrite go through the C runtime, which mangles these on Windows."""
    import numpy as np

    from whs_recorder.utils import read_image, write_image

    folder = tmp_path / "Bruxelles - Hôpital Saint-Élise"
    folder.mkdir()
    path = folder / "étape_01_résultat.png"

    frame = np.zeros((20, 30, 3), dtype=np.uint8)
    frame[:, :, 1] = 200

    write_image(str(path), frame)

    assert path.exists()
    assert np.array_equal(read_image(str(path)), frame)


def test_reading_an_image_that_is_not_there_returns_nothing(tmp_path):
    from whs_recorder.utils import read_image

    assert read_image(str(tmp_path / "missing.png")) is None


def test_reading_a_file_that_is_not_an_image_returns_nothing(tmp_path):
    from whs_recorder.utils import read_image

    path = tmp_path / "notes.png"
    path.write_text("this is not a picture", encoding="utf-8")

    assert read_image(str(path)) is None


def test_writing_makes_the_folder_it_needs(tmp_path):
    import numpy as np

    from whs_recorder.utils import write_image

    path = tmp_path / "runs" / "today" / "step.png"
    write_image(str(path), np.zeros((4, 4, 3), dtype=np.uint8))

    assert path.exists()


def test_writing_nothing_is_refused(tmp_path):
    from whs_recorder.utils import write_image

    with pytest.raises(ValueError, match="Nothing to write"):
        write_image(str(tmp_path / "step.png"), None)


def test_a_format_that_cannot_be_written_is_reported(tmp_path):
    """A silent failure here would cost a screenshot with no sign of it."""
    import numpy as np

    from whs_recorder.utils import write_image

    with pytest.raises(OSError):
        write_image(str(tmp_path / "step.zzz"), np.zeros((4, 4, 3), dtype=np.uint8))


@pytest.mark.parametrize(
    "name,expected",
    [
        ("Réception d'une ligne", "Réception d'une ligne"),   # accents are kept
        ("WHS: Receive / Putaway?", "WHS_ Receive _ Putaway_"),
        ("  spaced   out  ", "spaced out"),
        ("trailing dot.", "trailing dot"),
        ("", "Task guide"),
        ("   ", "Task guide"),
    ],
)
def test_a_recording_name_becomes_a_usable_file_name(name, expected):
    from whs_recorder.utils import safe_filename

    assert safe_filename(name) == expected


@pytest.mark.parametrize("reserved", ["CON", "nul", "COM1", "LPT9"])
def test_names_windows_reserves_are_stepped_around(reserved):
    from whs_recorder.utils import safe_filename

    assert safe_filename(reserved).startswith("_")


def test_a_document_can_be_written_under_its_accented_name(tmp_path):
    from whs_recorder.utils import safe_filename

    path = tmp_path / f"{safe_filename('Réception')}.docx"
    path.write_bytes(b"x")

    assert path.exists() and path.name == "Réception.docx"
