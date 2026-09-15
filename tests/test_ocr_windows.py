"""The Windows OCR engine path.

Windows OCR cannot run here, so its API is stood in for by fakes modelled on the
type stubs shipped in the winsdk and winrt-* wheels: the same names, the same
argument order, the same enum values, and a Rect whose numbers are floats as
WinRT declares them. That is enough to catch the mistakes this code could
actually make - the wrong pixel format, a buffer whose length was never set,
channels in the wrong order, a result read back incorrectly - rather than
leaving the whole path unexercised until someone runs it on Windows.
"""

import sys
import types

import cv2
import numpy as np
import pytest

from whs_recorder import ocr

BGRA8 = 87           # BitmapPixelFormat.BGRA8
ALPHA_IGNORE = 2     # BitmapAlphaMode.IGNORE
STARTED, COMPLETED, ERROR = 0, 1, 3


class Buffer(bytearray):
    """Stands in for Windows.Storage.Streams.Buffer.

    The real one hands out a writable memoryview, so this is a bytearray with a
    `length` of its own.
    """

    def __new__(cls, capacity):
        buffer = super().__new__(cls, int(capacity))
        buffer.capacity = int(capacity)
        buffer.length = 0
        return buffer


class Rect:
    """WinRT declares these as floats, so the reader has to round them itself."""

    def __init__(self, x, y, width, height):
        self.x, self.y = float(x), float(y)
        self.width, self.height = float(width), float(height)


class Word:
    def __init__(self, text, rect):
        self.text = text
        self.bounding_rect = rect


class Line:
    def __init__(self, words):
        self.words = words
        self.text = " ".join(w.text for w in words)


class Operation:
    """An IAsyncOperation that is still running until it is polled."""

    def __init__(self, result, polls_before_done=1, final_status=COMPLETED):
        self._result = result
        self._left = polls_before_done
        self._final = final_status

    @property
    def status(self):
        if self._left > 0:
            self._left -= 1
            return STARTED
        return self._final

    def get_results(self):
        return self._result


def fake_winrt(monkeypatch, lines=None, engine=True, result_status=COMPLETED):
    """Install a fake `winrt` package tree and return what it recorded."""
    seen = {"apartment": [], "bitmap": None, "buffer": None, "recognized": []}

    lines = lines if lines is not None else [
        Line([Word("Purchase", Rect(20.4, 100.6, 60.2, 14.9)),
              Word("receive", Rect(86.0, 100.0, 55.0, 14.0))]),
        Line([Word("PO000045", Rect(32.0, 130.0, 80.0, 16.0))]),
    ]

    class SoftwareBitmap:
        def __init__(self, buffer, fmt, width, height, alpha):
            self.buffer, self.format = buffer, fmt
            self.width, self.height, self.alpha = width, height, alpha

        @staticmethod
        def create_copy_from_buffer(buffer, fmt, width, height, alpha):
            bitmap = SoftwareBitmap(buffer, fmt, width, height, alpha)
            seen["bitmap"] = bitmap
            seen["buffer"] = bytes(buffer)
            return bitmap

    class OcrEngine:
        @staticmethod
        def try_create_from_user_profile_languages():
            return OcrEngine() if engine else None

        def recognize_async(self, bitmap):
            seen["recognized"].append(bitmap)
            return Operation(types.SimpleNamespace(lines=lines), final_status=result_status)

    system = types.ModuleType("winrt.system")
    system.MTA = 1
    system.init_apartment = lambda kind: seen["apartment"].append(kind)

    ocr_ns = types.ModuleType("winrt.windows.media.ocr")
    ocr_ns.OcrEngine = OcrEngine

    imaging = types.ModuleType("winrt.windows.graphics.imaging")
    imaging.SoftwareBitmap = SoftwareBitmap
    imaging.BitmapPixelFormat = types.SimpleNamespace(BGRA8=BGRA8, GRAY8=62)
    imaging.BitmapAlphaMode = types.SimpleNamespace(PREMULTIPLIED=0, STRAIGHT=1, IGNORE=ALPHA_IGNORE)

    streams = types.ModuleType("winrt.windows.storage.streams")
    streams.Buffer = Buffer

    for name, module in [
        ("winrt", types.ModuleType("winrt")),
        ("winrt.system", system),
        ("winrt.windows", types.ModuleType("winrt.windows")),
        ("winrt.windows.media", types.ModuleType("winrt.windows.media")),
        ("winrt.windows.media.ocr", ocr_ns),
        ("winrt.windows.graphics", types.ModuleType("winrt.windows.graphics")),
        ("winrt.windows.graphics.imaging", imaging),
        ("winrt.windows.storage", types.ModuleType("winrt.windows.storage")),
        ("winrt.windows.storage.streams", streams),
    ]:
        monkeypatch.setitem(sys.modules, name, module)

    return seen


@pytest.fixture(autouse=True)
def clean_state(monkeypatch):
    monkeypatch.setitem(ocr._state, "tesseract_path", "")
    monkeypatch.setitem(ocr._state, "prefer", "")
    monkeypatch.setitem(ocr._state, "warned", False)
    monkeypatch.delenv("WHS_OCR", raising=False)


@pytest.fixture
def frame():
    """A frame whose channels differ, so a channel-order mistake shows up."""
    image = np.zeros((4, 3, 3), dtype=np.uint8)
    image[:, :, 0] = 10   # blue
    image[:, :, 1] = 120  # green
    image[:, :, 2] = 240  # red
    return image


def test_words_are_read_back_with_their_boxes(monkeypatch, frame):
    fake_winrt(monkeypatch)

    words = ocr._read_windows(frame, min_confidence=40.0)

    assert [w.text for w in words] == ["Purchase", "receive", "PO000045"]
    assert (words[0].left, words[0].top, words[0].width, words[0].height) == (20, 100, 60, 14)
    assert all(isinstance(w.left, int) for w in words)


def test_words_keep_the_line_they_came_from(monkeypatch, frame):
    fake_winrt(monkeypatch)

    lines = ocr.group_lines(ocr._read_windows(frame, min_confidence=40.0))

    assert [l.text for l in lines] == ["Purchase receive", "PO000045"]


def test_every_word_clears_the_confidence_floor(monkeypatch, frame):
    """Windows OCR reports no score of its own, and only returns what it is sure of."""
    fake_winrt(monkeypatch)

    words = ocr._read_windows(frame, min_confidence=95.0)

    assert words and all(w.confidence == 100.0 for w in words)


def test_the_bitmap_is_described_the_way_windows_expects(monkeypatch, frame):
    seen = fake_winrt(monkeypatch)

    ocr._read_windows(frame, min_confidence=40.0)

    bitmap = seen["bitmap"]
    assert bitmap.format == BGRA8
    assert bitmap.alpha == ALPHA_IGNORE      # a screenshot is opaque
    assert (bitmap.width, bitmap.height) == (3, 4)   # width first, then height


def test_the_pixels_arrive_in_the_order_windows_reads_them(monkeypatch, frame):
    """A BGR frame has to become BGRA, not RGBA, or every word comes out wrong."""
    seen = fake_winrt(monkeypatch)

    ocr._read_windows(frame, min_confidence=40.0)

    written = np.frombuffer(seen["buffer"], dtype=np.uint8).reshape(4, 3, 4)
    assert np.array_equal(written, cv2.cvtColor(frame, cv2.COLOR_BGR2BGRA))
    assert written[0, 0, 0] == 10 and written[0, 0, 2] == 240


def test_the_buffer_reports_the_length_that_was_written(monkeypatch, frame):
    """A buffer left at length zero hands Windows an empty picture."""
    seen = fake_winrt(monkeypatch)
    captured = {}

    real_buffer = sys.modules["winrt.windows.storage.streams"].Buffer

    class WatchedBuffer(real_buffer):
        def __new__(cls, capacity):
            buffer = super().__new__(cls, capacity)
            captured["buffer"] = buffer
            return buffer

    sys.modules["winrt.windows.storage.streams"].Buffer = WatchedBuffer

    ocr._read_windows(frame, min_confidence=40.0)

    assert captured["buffer"].length == 4 * 3 * 4
    assert captured["buffer"].capacity == 4 * 3 * 4


def test_the_thread_gets_an_apartment_before_touching_winrt(monkeypatch, frame):
    seen = fake_winrt(monkeypatch)

    ocr._read_windows(frame, min_confidence=40.0)

    assert seen["apartment"] == [1]  # MTA


def test_an_apartment_already_set_up_is_not_an_error(monkeypatch, frame):
    fake_winrt(monkeypatch)
    system = sys.modules["winrt.system"]

    def already_done(_kind):
        raise RuntimeError("RPC_E_CHANGED_MODE")

    system.init_apartment = already_done

    assert ocr._read_windows(frame, min_confidence=40.0)


def test_no_language_pack_means_no_words(monkeypatch, frame):
    fake_winrt(monkeypatch, engine=False)

    assert ocr._read_windows(frame, min_confidence=40.0) == []
    assert ocr.windows_status().ready is False
    assert "language pack" in ocr.windows_status().detail


def test_an_operation_that_never_finishes_is_given_up_on(monkeypatch, frame):
    fake_winrt(monkeypatch)
    operation = Operation("ignored", polls_before_done=10_000)

    with pytest.raises(RuntimeError, match="did not finish"):
        ocr.wait_for_operation(operation, timeout=0.05)


def test_an_operation_that_fails_is_reported(monkeypatch, frame):
    fake_winrt(monkeypatch, result_status=ERROR)

    with pytest.raises(RuntimeError, match="did not finish"):
        ocr._read_windows(frame, min_confidence=40.0)


def test_a_failure_never_stops_a_recording(monkeypatch, frame, capsys):
    fake_winrt(monkeypatch, result_status=ERROR)
    monkeypatch.setattr(ocr, "windows_status", lambda: ocr.BackendStatus(ocr.WINDOWS, True))

    assert ocr.read_words(frame) == []
    assert "windows OCR engine failed" in capsys.readouterr().out.replace("the ", "")


def test_windows_is_reported_as_ready_once_the_packages_are_there(monkeypatch, frame):
    fake_winrt(monkeypatch)

    status = ocr.windows_status()

    assert status.ready is True
    assert "nothing to install" in status.detail
    assert ocr.active_backend() == ocr.WINDOWS


def test_an_empty_result_is_not_a_failure(monkeypatch, frame):
    fake_winrt(monkeypatch, lines=[])

    assert ocr._read_windows(frame, min_confidence=40.0) == []


# --------------------------------------------------------------------------
# The two WinRT packagings expose CreateCopyFromBuffer's alpha-mode form
# differently. Getting this wrong is not theoretical: the first run on a real
# Windows machine failed with "Invalid parameter count" because the call was
# written for winsdk and the winrt-* packages were installed.
# --------------------------------------------------------------------------


class Imaging:
    """A stand-in for the imaging namespace, in either packaging's shape."""

    def __init__(self, packaging):
        self.calls = []
        self.BitmapPixelFormat = types.SimpleNamespace(BGRA8=BGRA8, GRAY8=62)
        self.BitmapAlphaMode = types.SimpleNamespace(
            PREMULTIPLIED=0, STRAIGHT=1, IGNORE=ALPHA_IGNORE
        )

        calls = self.calls

        class SoftwareBitmap:
            @staticmethod
            def create_copy_from_buffer(buffer, fmt, width, height, alpha=None):
                if alpha is not None:
                    if packaging == "winrt":
                        # What the real binding does: it only has four.
                        raise RuntimeError("Invalid parameter count")
                    calls.append(("create_copy_from_buffer", 5, alpha))
                    return "bitmap"
                calls.append(("create_copy_from_buffer", 4, None))
                return "bitmap"

        if packaging == "winrt":
            def create_copy_with_alpha_from_buffer(buffer, fmt, width, height, alpha):
                calls.append(("create_copy_with_alpha_from_buffer", 5, alpha))
                return "bitmap"

            SoftwareBitmap.create_copy_with_alpha_from_buffer = staticmethod(
                create_copy_with_alpha_from_buffer
            )

        self.SoftwareBitmap = SoftwareBitmap


def test_the_winrt_packaging_uses_the_method_it_actually_has():
    """winrt-* renames the five-argument form rather than overloading."""
    imaging = Imaging("winrt")

    assert ocr.software_bitmap(imaging, b"", 360, 640) == "bitmap"
    assert imaging.calls == [("create_copy_with_alpha_from_buffer", 5, ALPHA_IGNORE)]


def test_the_winsdk_packaging_still_uses_its_overload():
    imaging = Imaging("winsdk")

    assert ocr.software_bitmap(imaging, b"", 360, 640) == "bitmap"
    assert imaging.calls == [("create_copy_from_buffer", 5, ALPHA_IGNORE)]


def test_a_packaging_with_neither_falls_back_to_four_arguments():
    """Still correct: the alpha the BGR conversion added is fully opaque."""
    imaging = Imaging("winrt")
    del imaging.SoftwareBitmap.create_copy_with_alpha_from_buffer

    assert ocr.software_bitmap(imaging, b"", 360, 640) == "bitmap"
    assert imaging.calls[-1] == ("create_copy_from_buffer", 4, None)


def test_the_alpha_channel_is_always_ignored():
    """A screenshot is opaque; premultiplied alpha would be the wrong answer."""
    for packaging in ("winrt", "winsdk"):
        imaging = Imaging(packaging)
        ocr.software_bitmap(imaging, b"", 10, 10)
        assert imaging.calls[0][2] == ALPHA_IGNORE


def test_a_reader_failure_is_remembered_for_the_report(monkeypatch, frame):
    """The reader swallows engine failures so a recording survives them, so the
    reason has to be kept or the report invents one."""
    backends = fake_winrt(monkeypatch)  # noqa: F841
    monkeypatch.setattr(ocr, "windows_status", lambda: ocr.BackendStatus(ocr.WINDOWS, True))

    def explode(frame, confidence):
        raise RuntimeError("Invalid parameter count")

    monkeypatch.setitem(ocr.READERS, ocr.WINDOWS, explode)

    assert ocr.read_words(frame) == []
    assert ocr.last_error() == "Invalid parameter count"


def test_a_reader_that_works_clears_the_last_failure(monkeypatch, frame):
    fake_winrt(monkeypatch)
    monkeypatch.setitem(ocr._state, "last_error", "an older failure")

    assert ocr._read_windows(frame, 40.0)
    ocr.read_words(frame)

    assert ocr.last_error() == ""
