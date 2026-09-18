"""Turning taps into steps, with the screen and the clock faked.

The one thing that matters most here is the first test: a person tapping at a
normal pace must not lose steps to the recorder waiting for a banner. The
recorder as first built kept three taps in eight at one tap a second, and no
test could have said so, because the logic lived in a closure that needed a
screen, a mouse and a window to run.
"""

import time

import numpy as np

from conftest import add_banner, make_screen

from whs_recorder.marker_recorder import StepTracker
from whs_recorder.recording import Recording, Step
from whs_recorder.suggest import Suggestion

GREEN = (0, 200, 0)


def screen_after_tap(n: int):
    """A screen that plainly differs from the one before: a new page, not a
    tooltip. `make_screen` alone varies only the colour of thin bands, which
    once shrunk to grey falls under the change threshold."""
    frame = make_screen(seed=n)
    frame[:, :, :] = np.where(frame == 235, 235 - (n * 37) % 160, frame)
    return frame


class FakeScreen:
    """A screen that shows whatever frame it was last told to."""

    def __init__(self, frame):
        self.frame = frame
        self.grabs = 0

    def grab(self):
        self.grabs += 1
        return self.frame


class SlowWatch:
    """A result watch that finds nothing and runs until it is told to stop,
    which is what a menu tap with no banner looks like.

    It keeps the last frame it saw *before* being stopped, as the real one
    does: a frame is only recorded when the wait ran out, never after the stop.
    """

    def __init__(self, screen, window=0.05):
        self.screen = screen
        self.window = window
        self.stopped = []

    def __call__(self, baseline, stop, holder):
        deadline = time.monotonic() + self.window
        holder["last"] = self.screen.frame
        while time.monotonic() < deadline and not stop.wait(0.01):
            holder["last"] = self.screen.frame
        self.stopped.append(stop.is_set())
        holder["frame"], holder["toast"] = holder["last"], ""


def tap(tracker, screen, frame, now, reason="mouse_click", click=(100, 100)):
    """One tap as the recorder sees it: the tap, the screen changing, the check."""
    tracker.notice_tap()
    screen.frame = frame
    return tracker.consider(reason, click, now)


def tracker_for(screen, watch, *, ask=None, suggest=None, saved=None, pictures=None,
                min_gap=0.75, window=2.5, mark_taps=True):
    recording = Recording(name="Taps")
    shots = saved if saved is not None else []
    frames = pictures if pictures is not None else {}

    def save_shot(frame, name):
        if frame is None:
            return ""
        shots.append(name)
        frames[name] = frame
        return name

    return recording, StepTracker(
        recording,
        grab=screen.grab,
        watch=watch,
        suggest=suggest,
        ask=ask,
        save_shot=save_shot,
        persist=lambda: None,
        announce=lambda step: None,
        diff_threshold=7.5,
        min_gap_sec=min_gap,
        result_window=window,
        mark_taps=mark_taps,
    )


# ------------------------------------------------------------ the main thing


def test_a_tap_a_second_with_no_banner_keeps_every_tap():
    """Eight taps at a normal pace, no result banner: eight steps, not three."""
    screen = FakeScreen(make_screen(seed=0))
    watch = SlowWatch(screen, window=2.5)  # the recorder's real window
    recording, tracker = tracker_for(screen, watch)

    for n in range(1, 9):
        tap(tracker, screen, screen_after_tap(n), now=n * 1.0)  # each tap: a new screen
    tracker.finish()

    assert len(recording.steps) == 8
    # Seven watches were ended by the tap that followed; the last ran out.
    assert watch.stopped == [True] * 7 + [False]


def test_the_next_tap_ends_the_previous_result_watch():
    screen = FakeScreen(make_screen(seed=0))
    watch = SlowWatch(screen)
    recording, tracker = tracker_for(screen, watch)

    first = tap(tracker, screen, screen_after_tap(1), now=1.0)
    assert first.result_img == ""  # still being watched

    tap(tracker, screen, screen_after_tap(2), now=2.0)

    assert watch.stopped == [True]  # cut short, not run out
    assert first.result_img.endswith("step_01_result.png")


def test_stopping_lets_the_last_watch_run_its_course():
    """The banner for the final step must not be lost to pressing Stop."""
    screen = FakeScreen(make_screen(seed=0))
    watch = SlowWatch(screen, window=0.05)
    recording, tracker = tracker_for(screen, watch)

    step = tap(tracker, screen, screen_after_tap(1), now=1.0)
    tracker.finish()

    assert watch.stopped == [False]  # ran out on its own
    assert step.result_img.endswith("step_01_result.png")


def test_a_banner_seen_during_the_watch_is_that_steps_result():
    screen = FakeScreen(make_screen(seed=0))
    banner = add_banner(screen_after_tap(1), GREEN)

    def watch_that_sees_a_banner(baseline, stop, holder):
        holder["last"] = banner
        holder["frame"], holder["toast"] = banner, "success"

    recording, tracker = tracker_for(screen, watch_that_sees_a_banner)

    step = tap(tracker, screen, screen_after_tap(1), now=1.0)
    tracker.finish()

    assert step.result_toast == "success"
    assert step.result_img.endswith("_result.png")


def test_the_screen_the_watch_left_behind_is_the_next_baseline():
    """A banner that has come and gone must not count as the next tap's change."""
    screen = FakeScreen(make_screen(seed=0))
    settled = screen_after_tap(1)

    def watch(baseline, stop, holder):
        holder["last"] = settled
        holder["frame"], holder["toast"] = settled, ""

    recording, tracker = tracker_for(screen, watch)

    tap(tracker, screen, screen_after_tap(1), now=1.0)

    # The next tap changes nothing compared with the settled screen.
    assert tap(tracker, screen, settled, now=2.0) is None
    assert np.array_equal(tracker.last_frame, settled)


def test_the_watch_stops_at_the_tap_so_the_baseline_is_the_screen_before_it():
    """Stopped only when the tap is looked at, 0.3s later, the watch would
    hand over the *new* screen as the baseline, and the tap would seem to
    have changed nothing. Four taps in eight were lost to exactly that."""
    screen = FakeScreen(make_screen(seed=0))
    watch = SlowWatch(screen)
    recording, tracker = tracker_for(screen, watch)

    tap(tracker, screen, screen_after_tap(1), now=1.0)

    tracker.notice_tap()                  # the tap
    screen.frame = screen_after_tap(2)    # the screen changed after it
    second = tracker.consider("mouse_click", (100, 100), now=2.0)

    assert watch.stopped == [True]        # ended by the tap, not by the check
    assert second is not None             # so the tap was seen as a change
    assert np.array_equal(tracker.last_frame, screen_after_tap(2))


# ------------------------------------------------------------- the basics


def test_a_tap_that_changes_nothing_is_not_a_step():
    screen = FakeScreen(make_screen(seed=0))
    recording, tracker = tracker_for(screen, SlowWatch(screen))

    assert tracker.consider("mouse_click", (100, 100), now=1.0) is None
    assert recording.steps == []


def test_taps_closer_than_the_gap_are_one_step():
    screen = FakeScreen(make_screen(seed=0))
    recording, tracker = tracker_for(screen, SlowWatch(screen), min_gap=0.75)

    tap(tracker, screen, screen_after_tap(1), now=1.0)
    tap(tracker, screen, screen_after_tap(2), now=1.3)  # a double-tap
    tracker.finish()

    assert len(recording.steps) == 1


def test_what_the_screen_says_becomes_the_step():
    screen = FakeScreen(make_screen(seed=0))

    def read(frame, click, before):
        return Suggestion(screen="Purchase receive", control="LP", value="LP000123")

    recording, tracker = tracker_for(screen, SlowWatch(screen), suggest=read)

    step = tap(tracker, screen, screen_after_tap(1), now=1.0, reason="enter", click=None)
    tracker.finish()

    assert (step.action, step.control, step.value, step.screen) == (
        "scan", "LP", "LP000123", "Purchase receive"
    )


def test_a_tap_keeps_no_value_even_when_the_screen_showed_new_text():
    screen = FakeScreen(make_screen(seed=0))
    recording, tracker = tracker_for(
        screen, SlowWatch(screen),
        suggest=lambda *_: Suggestion(control="Inbound", value="Available actions"),
    )

    step = tap(tracker, screen, screen_after_tap(1), now=1.0)
    tracker.finish()

    assert step.action == "tap"
    assert step.value == ""


def test_the_screen_name_carries_over_to_a_step_that_could_not_read_it():
    screen = FakeScreen(make_screen(seed=0))
    readings = iter([Suggestion(screen="Main menu", control="Inbound"), Suggestion(control="OK")])
    recording, tracker = tracker_for(
        screen, SlowWatch(screen), suggest=lambda *_: next(readings)
    )

    tap(tracker, screen, screen_after_tap(1), now=1.0)
    second = tap(tracker, screen, screen_after_tap(2), now=2.0)
    tracker.finish()

    assert second.screen == "Main menu"


def test_the_action_screenshot_is_saved_at_the_tap():
    screen = FakeScreen(make_screen(seed=0))
    saved = []
    recording, tracker = tracker_for(screen, SlowWatch(screen), saved=saved)

    step = tap(tracker, screen, screen_after_tap(1), now=1.0)

    assert step.action_img == "step_01_action.png"
    assert saved == ["step_01_action.png"]


# ------------------------------------------------------- asking each step


def test_a_popup_that_is_cancelled_records_nothing_and_stops_the_watch():
    screen = FakeScreen(make_screen(seed=0))
    watch = SlowWatch(screen)
    recording, tracker = tracker_for(screen, watch, ask=lambda *_: None)

    assert tap(tracker, screen, screen_after_tap(1), now=1.0) is None
    assert recording.steps == []
    assert watch.stopped == [True]


def test_a_popup_answer_is_the_step():
    screen = FakeScreen(make_screen(seed=0))
    answered = Step(action="tap", control="Inbound")
    recording, tracker = tracker_for(screen, SlowWatch(screen), ask=lambda *_: answered)

    assert tap(tracker, screen, screen_after_tap(1), now=1.0) is answered
    assert recording.steps == [answered]


# ------------------------------------------------------------- the claim


def test_a_dialog_holds_the_recorder_and_a_tap_meanwhile_is_refused():
    screen = FakeScreen(make_screen(seed=0))
    recording, tracker = tracker_for(screen, SlowWatch(screen))

    assert tracker.claim() is True
    assert tracker.busy is True
    assert tap(tracker, screen, screen_after_tap(1), now=1.0) is None
    tracker.release()

    assert tap(tracker, screen, screen_after_tap(2), now=2.0) is not None


def test_writing_a_step_does_not_hold_the_recorder_for_the_result_window():
    """The whole point: the recorder is free again the moment the step is written."""
    screen = FakeScreen(make_screen(seed=0))
    recording, tracker = tracker_for(screen, SlowWatch(screen, window=60.0))

    tap(tracker, screen, screen_after_tap(1), now=1.0)

    assert tracker.busy is False
    tracker._settle()  # end the sixty-second watch so the test does too


def test_the_result_is_written_even_when_the_persist_step_is_slow(monkeypatch):
    """Persisting happens twice per step: once at the tap, once with the result."""
    screen = FakeScreen(make_screen(seed=0))
    writes = []
    recording = Recording(name="Taps")
    tracker = StepTracker(
        recording, grab=screen.grab, watch=SlowWatch(screen, window=0.01),
        suggest=None, ask=None, save_shot=lambda f, n: n if f is not None else "",
        persist=lambda: writes.append(len(recording.steps)),
        announce=lambda step: None,
        diff_threshold=7.5, min_gap_sec=0.75, result_window=0.01,
    )

    tap(tracker, screen, screen_after_tap(1), now=1.0)
    tracker.finish()

    assert writes == [1, 1]


# ------------------------------------------------------- the step's picture


def test_the_picture_is_the_screen_as_it_was_tapped_not_the_reaction():
    """A third of a second after a tap the app is greyed out or loading. The
    step keeps the screen the person acted on, grabbed at the tap itself."""
    screen = FakeScreen(make_screen(seed=0))
    pictures = {}
    recording, tracker = tracker_for(screen, SlowWatch(screen), pictures=pictures, mark_taps=False)

    tracker.notice_tap()                     # the tap, on the untouched screen
    greyed = (screen_after_tap(1) // 2).astype(np.uint8)
    screen.frame = greyed                    # and the app's greyed reaction
    step = tracker.consider("mouse_click", (100, 100), now=1.0)

    assert step is not None
    assert np.array_equal(pictures[step.action_img], make_screen(seed=0))


def test_the_tap_is_marked_on_the_picture():
    screen = FakeScreen(make_screen(seed=0))
    pictures = {}
    recording, tracker = tracker_for(screen, SlowWatch(screen), pictures=pictures)

    step = tap(tracker, screen, screen_after_tap(1), now=1.0, click=(100, 100))

    picture = pictures[step.action_img]
    assert not np.array_equal(picture, make_screen(seed=0))   # something was drawn
    around = picture[100 - 40:100 + 40, 100 - 40:100 + 40]
    assert (around[:, :, 2] > 180).any()                      # red, around the tap
    centre = picture[100 - 8:100 + 8, 100 - 8:100 + 8]
    assert np.array_equal(centre, make_screen(seed=0)[92:108, 92:108])  # not on the target
    far = picture[400:440, 200:240]
    assert np.array_equal(far, make_screen(seed=0)[400:440, 200:240])  # elsewhere untouched


def test_the_marker_never_touches_the_baseline_the_banner_is_judged_against():
    screen = FakeScreen(make_screen(seed=0))
    baselines = []

    def watch(baseline, stop, holder):
        baselines.append(baseline)
        holder["last"] = screen.frame
        holder["frame"], holder["toast"] = screen.frame, ""

    recording, tracker = tracker_for(screen, watch)
    tap(tracker, screen, screen_after_tap(1), now=1.0, click=(100, 100))

    assert np.array_equal(baselines[0], make_screen(seed=0))  # no ring on it


def test_a_tap_outside_the_region_leaves_the_picture_unmarked():
    screen = FakeScreen(make_screen(seed=0))
    pictures = {}
    recording, tracker = tracker_for(screen, SlowWatch(screen), pictures=pictures)

    step = tap(tracker, screen, screen_after_tap(1), now=1.0, click=None)

    assert np.array_equal(pictures[step.action_img], make_screen(seed=0))


def test_the_control_is_read_off_the_screen_that_was_tapped():
    """After tapping "Inbound" the screen is a different one; the button is
    on the screen from before the tap."""
    screen = FakeScreen(make_screen(seed=0))
    handed = {}

    def read(frame, click, before):
        handed["frame"], handed["before"] = frame, before
        return Suggestion(control="Inbound")

    recording, tracker = tracker_for(screen, SlowWatch(screen), suggest=read)
    tap(tracker, screen, screen_after_tap(1), now=1.0)

    assert np.array_equal(handed["before"], make_screen(seed=0))
    assert np.array_equal(handed["frame"], screen_after_tap(1))


def test_the_change_is_measured_from_the_screen_at_the_tap():
    """The baseline for 'did this tap change anything' is the screen at the
    tap, not a frame from some time before it."""
    screen = FakeScreen(make_screen(seed=0))
    recording, tracker = tracker_for(screen, SlowWatch(screen))

    # The screen changed on its own, without a tap - an animation settling.
    screen.frame = screen_after_tap(3)
    tracker.notice_tap()                     # a tap on that changed screen,
    step = tracker.consider("mouse_click", (100, 100), now=1.0)   # changing nothing

    assert step is None


def test_marking_can_be_turned_off():
    from whs_recorder.marker_recorder import draw_tap_marker

    frame = make_screen(seed=0)
    assert draw_tap_marker(frame, None) is frame
    assert draw_tap_marker(frame, (-5, 10)) is frame
    assert draw_tap_marker(frame, (10, 10_000)) is frame
    assert draw_tap_marker(None, (10, 10)) is None
