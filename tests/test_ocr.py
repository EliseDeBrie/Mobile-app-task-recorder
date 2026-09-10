import os

import numpy as np
import pytest

from whs_recorder import ocr
from whs_recorder.ocr import BackendStatus, TextLine


@pytest.fixture(autouse=True)
def clean_state(monkeypatch):
    """Each test starts with no forced engine and no remembered path."""
    monkeypatch.setitem(ocr._state, "tesseract_path", "")
    monkeypatch.setitem(ocr._state, "prefer", "")
    monkeypatch.setitem(ocr._state, "warned", False)
    monkeypatch.delenv("WHS_OCR", raising=False)
    monkeypatch.delenv("WHS_TESSERACT", raising=False)


def backends(monkeypatch, windows=False, tesseract=False):
    monkeypatch.setattr(ocr, "windows_status", lambda: BackendStatus(ocr.WINDOWS, windows))
    monkeypatch.setattr(ocr, "tesseract_status", lambda: BackendStatus(ocr.TESSERACT, tesseract))


def test_windows_is_preferred_because_it_needs_no_install(monkeypatch):
    backends(monkeypatch, windows=True, tesseract=True)
    assert ocr.active_backend() == ocr.WINDOWS


def test_tesseract_is_used_when_windows_ocr_is_not_there(monkeypatch):
    backends(monkeypatch, windows=False, tesseract=True)
    assert ocr.active_backend() == ocr.TESSERACT


def test_no_engine_means_no_ocr(monkeypatch):
    backends(monkeypatch)
    assert ocr.active_backend() == ""
    assert ocr.available() is False


def test_an_engine_can_be_forced(monkeypatch):
    backends(monkeypatch, windows=True, tesseract=True)
    ocr.configure(prefer="tesseract")
    assert ocr.active_backend() == ocr.TESSERACT


def test_forcing_an_engine_that_is_not_ready_falls_back_to_none(monkeypatch):
    backends(monkeypatch, windows=False, tesseract=True)
    ocr.configure(prefer="windows")
    assert ocr.active_backend() == ""


def test_ocr_can_be_turned_off_entirely(monkeypatch):
    backends(monkeypatch, windows=True, tesseract=True)
    ocr.configure(prefer="none")
    assert ocr.active_backend() == ""


def test_the_environment_can_choose_the_engine(monkeypatch):
    backends(monkeypatch, windows=True, tesseract=True)
    monkeypatch.setenv("WHS_OCR", "tesseract")
    assert ocr.active_backend() == ocr.TESSERACT


def test_an_explicit_tesseract_path_wins(tmp_path, monkeypatch):
    binary = tmp_path / "tesseract"
    binary.write_text("", encoding="utf-8")
    monkeypatch.setattr(ocr.shutil, "which", lambda name: "/usr/bin/tesseract")

    ocr.configure(tesseract_path=str(binary))

    assert ocr.tesseract_path() == str(binary)


def test_a_portable_copy_is_found_without_an_installer(tmp_path, monkeypatch):
    """The usual Tesseract installer wants an administrator; a portable copy does not."""
    folder = tmp_path / "tesseract"
    folder.mkdir()
    name = "tesseract.exe" if os.name == "nt" else "tesseract"
    (folder / name).write_text("", encoding="utf-8")

    monkeypatch.setattr(ocr, "PORTABLE_DIRS", (str(folder),))
    monkeypatch.setattr(ocr.shutil, "which", lambda n: None)

    assert ocr.tesseract_path() == str(folder / name)


def test_the_environment_variable_is_honoured(tmp_path, monkeypatch):
    binary = tmp_path / "tesseract"
    binary.write_text("", encoding="utf-8")
    monkeypatch.setenv("WHS_TESSERACT", str(binary))
    monkeypatch.setattr(ocr.shutil, "which", lambda n: None)

    assert ocr.tesseract_path() == str(binary)


def test_a_path_that_is_not_there_falls_back_to_the_search_path(monkeypatch):
    monkeypatch.setattr(ocr, "PORTABLE_DIRS", ())
    monkeypatch.setattr(ocr.shutil, "which", lambda n: "/usr/bin/tesseract")
    ocr.configure(tesseract_path="/nowhere/tesseract")

    assert ocr.tesseract_path() == "/usr/bin/tesseract"


def test_reading_without_an_engine_says_so_once(monkeypatch, capsys):
    backends(monkeypatch)
    frame = np.zeros((10, 10, 3), dtype=np.uint8)

    assert ocr.read_words(frame) == []
    assert ocr.read_words(frame) == []

    out = capsys.readouterr().out
    assert out.count("no OCR engine available") == 1
    assert "whs-recorder check" in out


def test_a_broken_engine_never_stops_a_recording(monkeypatch, capsys):
    backends(monkeypatch, tesseract=True)

    def explode(frame, confidence):
        raise RuntimeError("tesseract died")

    monkeypatch.setitem(ocr.READERS, ocr.TESSERACT, explode)

    assert ocr.read_words(np.zeros((10, 10, 3), dtype=np.uint8)) == []
    assert "tesseract died" in capsys.readouterr().out


def test_reading_nothing_returns_nothing():
    assert ocr.read_words(None) == []


def test_words_on_one_line_are_grouped(monkeypatch):
    words = [
        TextLine("Purchase", 20, 100, 60, 14, 90.0, (1, 1, 1)),
        TextLine("order", 86, 100, 40, 14, 90.0, (1, 1, 1)),
        TextLine("PO000045", 32, 130, 80, 16, 90.0, (1, 1, 2)),
    ]
    lines = ocr.group_lines(words)

    assert [l.text for l in lines] == ["Purchase order", "PO000045"]
    assert lines[0].left == 20 and lines[0].right == 126


def test_redaction_gets_word_boxes(monkeypatch):
    backends(monkeypatch, tesseract=True)
    monkeypatch.setitem(
        ocr.READERS, ocr.TESSERACT,
        lambda frame, conf: [TextLine("LP000123", 10, 20, 70, 15, 90.0)],
    )

    assert ocr.words_with_boxes(np.zeros((10, 10, 3), dtype=np.uint8)) == [
        ("LP000123", (10, 20, 70, 15))
    ]


def test_either_winrt_packaging_will_do(monkeypatch):
    """winsdk covers Python up to 3.11; the winrt-* packages cover later ones."""
    import importlib

    seen = []

    def only_winrt(name):
        seen.append(name)
        if name.startswith("winsdk"):
            raise ImportError("no winsdk here")
        return f"module:{name}"

    monkeypatch.setattr(importlib, "import_module", only_winrt)

    modules = ocr.winrt_modules()

    assert modules["ocr"] == "module:winrt.windows.media.ocr"
    assert not any(n.startswith("winsdk") for n in seen)


def test_the_older_packaging_is_used_when_the_new_one_is_absent(monkeypatch):
    import importlib

    def only_winsdk(name):
        if name.startswith("winrt"):
            raise ImportError("no winrt here")
        return f"module:{name}"

    monkeypatch.setattr(importlib, "import_module", only_winsdk)

    assert ocr.winrt_modules()["ocr"] == "module:winsdk.windows.media.ocr"


def test_no_winrt_packaging_at_all_means_no_windows_engine(monkeypatch):
    import importlib

    def nothing(name):
        raise ImportError("not here")

    monkeypatch.setattr(importlib, "import_module", nothing)

    assert ocr.winrt_modules() is None
    assert ocr.windows_engine() is None
    assert ocr.windows_status().ready is False
    assert "administrator" in ocr.windows_status().remedy.lower()
