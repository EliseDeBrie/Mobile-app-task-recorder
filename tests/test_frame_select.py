import numpy as np
import pytest

from conftest import FakeCapture, add_banner, make_screen

from whs_recorder.frame_select import (
    ToastDetection,
    choose_frame,
    choose_result_frame,
    detect_toast,
)

GREEN = (0, 200, 0)
RED = (0, 0, 220)
AMBER = (0, 170, 240)


def test_plain_screen_has_no_toast(screen):
    assert detect_toast(screen).found is False


@pytest.mark.parametrize(
    "color,family",
    [(GREEN, "success"), (RED, "error"), (AMBER, "warning")],
)
def test_banner_colour_maps_to_family(screen, color, family):
    found = detect_toast(add_banner(screen, color), baseline=screen)
    assert found.found is True
    assert found.family == family
    assert 555 <= found.y1 <= 565
    assert 595 <= found.y2 <= 605


def test_static_header_is_not_reported_as_a_message(screen):
    """A coloured bar already present at the marker is app chrome, not a result."""
    with_header = add_banner(screen, GREEN, y1=0, y2=40)
    assert detect_toast(with_header, baseline=with_header).found is False


def test_full_screen_colour_is_not_a_banner(screen):
    flooded = np.full_like(screen, GREEN, dtype=np.uint8)
    assert detect_toast(flooded, baseline=screen).found is False


def test_narrow_badge_is_not_a_banner(screen):
    badge = screen.copy()
    badge[560:600, 300:340] = GREEN  # coloured, but nowhere near full width
    assert detect_toast(badge, baseline=screen).found is False


def test_choose_result_frame_prefers_the_frame_with_the_banner():
    """The banner appears late, well past the legacy 0.6s / 1.2s offsets."""
    frames = [make_screen(seed=i) for i in range(30)]
    frames[22] = add_banner(frames[22], GREEN)
    cap = FakeCapture(frames, fps=10.0)

    choice = choose_result_frame(cap, 10.0, t_sec=2.0, baseline=frames[20], window_sec=2.5)

    assert choice.mode == "toast"
    assert choice.has_toast
    assert choice.toast.family == "success"
    assert choice.offset == pytest.approx(0.2, abs=0.15)


def test_choose_result_frame_falls_back_to_offsets_without_a_banner():
    frames = [make_screen(seed=i) for i in range(30)]
    cap = FakeCapture(frames, fps=10.0)

    choice = choose_result_frame(cap, 10.0, t_sec=1.0, baseline=frames[10], offsets=[0.6, 1.2])

    assert choice.mode in ("strict", "relaxed", "exact")
    assert choice.has_toast is False
    assert choice.offset in (0.6, 1.2)


def test_toast_detection_can_be_switched_off():
    frames = [make_screen(seed=i) for i in range(30)]
    frames[22] = add_banner(frames[22], GREEN)
    cap = FakeCapture(frames, fps=10.0)

    choice = choose_result_frame(
        cap, 10.0, t_sec=2.0, baseline=frames[20], offsets=[0.6], use_toast_detection=False
    )

    assert choice.mode != "toast"
    assert choice.offset == 0.6


def test_choose_frame_returns_a_sharp_frame():
    frames = [make_screen(seed=i) for i in range(20)]
    cap = FakeCapture(frames, fps=10.0)

    choice = choose_frame(cap, 10.0, t_sec=1.0)

    assert choice.frame is not None
    assert choice.mode == "strict"


def test_choose_frame_reports_none_past_the_end():
    cap = FakeCapture([], fps=10.0)
    assert choose_frame(cap, 10.0, t_sec=1.0).mode == "none"


def test_toast_detection_ignores_greyscale_input():
    assert detect_toast(np.zeros((100, 100), dtype=np.uint8)) == ToastDetection()
