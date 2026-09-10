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
