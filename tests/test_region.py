import numpy as np
import pytest

from conftest import make_screen

from whs_recorder.region import (
    MIN_SIDE,
    Region,
    normalise_box,
    parse_region,
    popup_position,
)

SCREEN = (0, 0, 1920, 1080)


@pytest.mark.parametrize(
    "corners",
    [(100, 80, 400, 500), (400, 500, 100, 80), (100, 500, 400, 80), (400, 80, 100, 500)],
)
def test_a_drag_in_any_direction_gives_the_same_region(corners):
    region = normalise_box(*corners, source="select")
    assert (region.left, region.top, region.width, region.height) == (100, 80, 300, 420)
    assert region.source == "select"


def test_a_stray_click_is_not_a_selection():
    assert normalise_box(100, 100, 100, 100) is None
    assert normalise_box(100, 100, 100 + MIN_SIDE - 1, 400) is None


@pytest.mark.parametrize(
    "text", ["100,80,720,1280", "100 80 720 1280", "100x80x720x1280", " 100, 80, 720, 1280 "]
)
def test_region_text_forms(text):
    region = parse_region(text)
    assert (region.left, region.top, region.width, region.height) == (100, 80, 720, 1280)


def test_full_and_empty_mean_the_whole_monitor():
    assert parse_region("full") is None
    assert parse_region("") is None
    assert parse_region(None) is None


@pytest.mark.parametrize("text", ["100,80,720", "100,80,720,1280,5", "a,b,c,d"])
def test_unreadable_region_text_is_rejected(text):
    with pytest.raises(ValueError, match="Cannot read region"):
        parse_region(text)


def test_a_region_too_small_to_capture_is_rejected():
    with pytest.raises(ValueError, match="too small"):
        parse_region("10,10,4,4")


def test_crop_cuts_the_app_out_of_a_full_screen_frame():
    frame = make_screen(width=1920, height=1080)
    region = Region(100, 80, 360, 640)

    cropped = region.crop(frame)

    assert cropped.shape[:2] == (640, 360)
    assert np.array_equal(cropped, frame[80:720, 100:460])


def test_crop_is_clamped_to_the_frame():
    frame = make_screen(width=400, height=300)
    assert Region(300, 200, 400, 400).crop(frame).shape[:2] == (100, 100)


def test_crop_of_a_region_entirely_outside_the_frame_returns_the_frame():
    frame = make_screen(width=400, height=300)
    assert Region(900, 900, 100, 100).crop(frame).shape == frame.shape


def test_crop_of_nothing_is_nothing():
    assert Region(0, 0, 10, 10).crop(None) is None


def test_region_round_trips_through_a_dict():
    region = Region(10, 20, 300, 600, "select")
    assert Region.from_dict(region.to_dict()) == region
    assert Region.from_dict(None) is None


def test_monitor_dict_matches_what_mss_grabs():
    assert Region(10, 20, 300, 600).to_monitor() == {
        "left": 10, "top": 20, "width": 300, "height": 600,
    }


def test_region_describes_itself():
    assert Region(10, 20, 300, 600, "select").describe() == "300x600 at 10,20 (select)"


def test_popup_goes_to_the_right_of_the_app_when_it_fits():
    region = Region(100, 80, 360, 640)
    assert popup_position(region, SCREEN, popup_size=(420, 640)) == (472, 80)


def test_popup_goes_to_the_left_when_the_right_is_full():
    region = Region(1400, 100, 480, 900)
    assert popup_position(region, SCREEN, popup_size=(420, 640)) == (968, 100)


def test_popup_goes_below_when_neither_side_fits():
    region = Region(0, 0, 1920, 300)
    x, y = popup_position(region, SCREEN, popup_size=(420, 640))
    assert y == 312


def test_popup_goes_above_when_only_the_top_is_free():
    region = Region(0, 700, 1920, 380)
    x, y = popup_position(region, SCREEN, popup_size=(420, 640))
    assert y == 48


def test_popup_falls_back_to_the_far_corner_when_the_app_fills_the_screen():
    region = Region(0, 0, 1920, 1080)
    assert popup_position(region, SCREEN, popup_size=(420, 640)) == (1488, 428)


def test_popup_never_leaves_the_screen():
    region = Region(100, 900, 360, 180)
    x, y = popup_position(region, SCREEN, popup_size=(420, 640))
    assert 0 <= x <= 1920 - 420
    assert 0 <= y <= 1080 - 640


def test_popup_without_a_region_sits_in_the_corner():
    assert popup_position(None, SCREEN) == (12, 12)


def test_resolve_region_reads_explicit_coordinates():
    from whs_recorder.region import resolve_region

    region = resolve_region("100,80,720,1280")
    assert (region.left, region.width) == (100, 720)


def test_resolve_region_treats_full_as_the_whole_monitor():
    from whs_recorder.region import resolve_region

    assert resolve_region("full") is None
    assert resolve_region("") is None


def test_resolve_region_reports_a_window_that_is_not_open(monkeypatch):
    import whs_recorder.region as region_module

    monkeypatch.setattr(region_module, "region_from_window", lambda title: None)

    with pytest.raises(RuntimeError, match="No window matches"):
        region_module.resolve_region("window:Warehouse")


def test_window_lookup_explains_the_missing_dependency(monkeypatch):
    import builtins

    import whs_recorder.region as region_module

    real_import = builtins.__import__

    def no_pygetwindow(name, *args, **kwargs):
        if name == "pygetwindow":
            raise ImportError("no module")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_pygetwindow)

    with pytest.raises(RuntimeError, match="pygetwindow"):
        region_module.region_from_window("Warehouse")
