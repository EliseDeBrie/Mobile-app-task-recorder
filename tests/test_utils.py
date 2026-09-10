import os

import numpy as np

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
