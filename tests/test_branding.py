"""The program's icon, and getting it onto a window.

An icon that quietly fails to load is how the executable ended up showing
PyInstaller's feather for a whole release, so this checks it is found both from
a checkout and from inside a packaged build.
"""

import os

import pytest

from conftest import open_window

from whs_recorder import branding


def test_the_icon_ships_inside_the_package():
    path = branding.icon_path()

    assert path is not None
    assert os.path.isfile(path)
    assert os.path.basename(path) == "icon.png"


def test_the_icon_is_a_real_png():
    with open(branding.icon_path(), "rb") as f:
        assert f.read(8) == b"\x89PNG\r\n\x1a\n"


def test_a_packaged_build_looks_where_pyinstaller_unpacked_it(monkeypatch, tmp_path):
    unpacked = tmp_path / "whs_recorder"
    unpacked.mkdir()
    bundled = unpacked / "icon.png"
    bundled.write_bytes(b"\x89PNG\r\n\x1a\n")

    monkeypatch.setattr("sys._MEIPASS", str(tmp_path), raising=False)

    assert branding.icon_path() == str(bundled)


def test_a_build_missing_its_icon_says_so_rather_than_failing(monkeypatch, tmp_path):
    monkeypatch.setattr(branding, "ICON_FILE", "not-here.png")

    assert branding.icon_path() is None


def test_the_icon_reaches_the_window():
    tk = pytest.importorskip("tkinter")

    window = open_window(tk.Tk)
    try:
        assert branding.apply_icon(window) is True
        # Held on the window, or Tk drops it and the icon goes blank.
        assert window._whs_icon.width() > 0
    finally:
        window.destroy()


def test_a_missing_icon_leaves_the_window_alone(monkeypatch):
    tk = pytest.importorskip("tkinter")

    monkeypatch.setattr(branding, "icon_path", lambda: None)
    window = open_window(tk.Tk)
    try:
        assert branding.apply_icon(window) is False
    finally:
        window.destroy()


def test_the_launcher_and_the_review_window_both_carry_it(tmp_path):
    from whs_recorder.app import Launcher
    from whs_recorder.recording import Recording, Step
    from whs_recorder.review import Review

    r = Recording(name="With an icon")
    r.add(Step(action="tap", control="OK"))
    path = tmp_path / "recording.json"
    r.save(str(path))

    launcher = open_window(Launcher)
    try:
        assert hasattr(launcher.root, "_whs_icon")
        review = Review(str(path))
        try:
            assert hasattr(review.root, "_whs_icon")
        finally:
            review.root.destroy()
    finally:
        launcher.root.destroy()
