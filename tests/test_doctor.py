import pytest

from whs_recorder import doctor, ocr
from whs_recorder.doctor import CheckResult, report
from whs_recorder.ocr import BackendStatus


def test_the_report_covers_everything_a_recording_needs():
    names = [r.name for r in doctor.run_checks()]

    assert "Python" in names
    assert "opencv-python" in names
    assert "mss" in names
    assert "pynput" in names
    assert "tkinter" in names
    assert "Screen capture" in names
    assert any(n.startswith("OCR") for n in names)


def test_a_clean_machine_reports_that_nothing_is_missing():
    results = [CheckResult("Python", True, "3.12.0"), CheckResult("mss", True, "capturing")]

    text = report(results)

    assert "Everything needed to record and build is present." in text
    assert "None of it needs administrator rights." in text


def test_a_missing_requirement_is_counted_and_explained():
    results = [
        CheckResult("Python", True, "3.12.0"),
        CheckResult("mss", False, "missing", "pip install --user mss"),
    ]

    text = report(results)

    assert "MISSING mss" in text
    assert "pip install --user mss" in text
    assert "1 required item(s) missing" in text


def test_an_optional_gap_does_not_count_as_missing():
    results = [
        CheckResult("Python", True, "3.12.0"),
        CheckResult("OCR: windows", False, "not installed", "pip install --user winsdk", optional=True),
    ]

    text = report(results)

    assert "Everything needed to record and build is present." in text
    assert "pip install --user winsdk" in text


def test_every_remedy_avoids_needing_an_administrator():
    """The whole point: a consultant on a customer machine is not an administrator."""
    remedies = [r.remedy for r in doctor.run_checks() if r.remedy]

    assert remedies
    for remedy in remedies:
        assert "administrator" not in remedy.lower() or "no administrator" in remedy.lower()
        assert "sudo" not in remedy.lower()
        if remedy.startswith("pip install"):
            assert "--user" in remedy


def test_the_tkinter_remedy_matches_the_platform(monkeypatch):
    monkeypatch.setattr(doctor.os, "name", "nt")
    assert "Python installer" in doctor._tkinter_remedy()

    monkeypatch.setattr(doctor.os, "name", "posix")
    assert "python3-tk" in doctor._tkinter_remedy()


def test_the_ocr_section_names_the_engine_in_use(monkeypatch):
    monkeypatch.setattr(ocr, "windows_status", lambda: BackendStatus(ocr.WINDOWS, True, "built in"))
    monkeypatch.setattr(ocr, "tesseract_status", lambda: BackendStatus(ocr.TESSERACT, False, "no binary", "unpack it"))

    results = doctor.check_ocr()

    assert any(r.name == "OCR: windows" and "in use" in r.detail for r in results)


def test_no_ocr_at_all_is_reported_as_survivable(monkeypatch):
    monkeypatch.setattr(ocr, "windows_status", lambda: BackendStatus(ocr.WINDOWS, False, "missing", "install"))
    monkeypatch.setattr(ocr, "tesseract_status", lambda: BackendStatus(ocr.TESSERACT, False, "missing", "install"))

    results = doctor.check_ocr()
    text = report(results)

    assert "the popup will not fill itself in" in text
    assert "everything else still works" in text
    assert "required item(s) missing" not in text


def test_the_python_check_reads_a_windows_install_location(monkeypatch):
    """"Program Files" has a space in it, which an earlier check missed."""
    monkeypatch.setattr(doctor.os, "name", "nt")

    monkeypatch.setattr(doctor.sys, "prefix", r"C:\Users\elise\AppData\Local\Programs\Python\Python312")
    assert "installed for this user" in doctor.check_python().detail

    monkeypatch.setattr(doctor.sys, "prefix", r"C:\Program Files\Python312")
    assert "for all users" in doctor.check_python().detail

    monkeypatch.setattr(
        doctor.sys, "prefix",
        r"C:\Program Files\WindowsApps\PythonSoftwareFoundation.Python.3.12_3.12.100.0_x64__qbz5n2kfra8p0",
    )
    assert "Microsoft Store" in doctor.check_python().detail


def test_the_python_check_stays_quiet_about_location_off_windows(monkeypatch):
    monkeypatch.setattr(doctor.os, "name", "posix")
    assert "installed" not in doctor.check_python().detail


def test_the_check_actually_reads_a_test_image(monkeypatch):
    """Loading an engine proves nothing; reading something does."""
    monkeypatch.setattr(ocr, "active_backend", lambda: "windows")
    monkeypatch.setattr(
        ocr, "read_lines",
        lambda frame, *a, **k: [ocr.TextLine("WHS RECORDER 12345", 0, 0, 100, 20, 100.0)],
    )

    result = doctor.check_ocr_reads()

    assert result.ok is True
    assert "windows" in result.name
    assert "WHS RECORDER 12345" in result.detail


def test_an_engine_that_reads_gibberish_is_reported(monkeypatch):
    monkeypatch.setattr(ocr, "active_backend", lambda: "tesseract")
    monkeypatch.setattr(ocr, "read_lines", lambda frame, *a, **k: [ocr.TextLine("|||", 0, 0, 10, 10)])

    result = doctor.check_ocr_reads()

    assert result.ok is False
    assert result.optional is True
    assert "--ocr" in result.remedy


def test_an_engine_that_throws_while_reading_is_reported(monkeypatch):
    monkeypatch.setattr(ocr, "active_backend", lambda: "windows")

    def explode(frame, *a, **k):
        raise RuntimeError("OCR engine unavailable")

    monkeypatch.setattr(ocr, "read_lines", explode)

    result = doctor.check_ocr_reads()

    assert result.ok is False
    assert "OCR engine unavailable" in result.detail
    assert "--no-suggest" in result.remedy


def test_the_read_check_is_skipped_without_an_engine(monkeypatch):
    monkeypatch.setattr(ocr, "active_backend", lambda: "")

    result = doctor.check_ocr_reads()

    assert result.ok is False
    assert result.optional is True
    assert "skipped" in result.detail


def test_the_test_image_carries_the_text_it_claims():
    image = doctor.selftest_image()

    assert image.shape[2] == 3
    assert image.min() < 60   # dark text
    assert image.max() > 200  # on a light background


def test_a_package_that_is_not_installed_is_named_as_missing():
    state, _ = doctor._probe("a_package_nobody_has_installed")
    assert state == "missing"


def test_a_package_that_is_installed_reads_as_ok():
    assert doctor._probe("json")[0] == "ok"


def test_a_package_that_loads_badly_is_not_called_missing(monkeypatch):
    """pynput is installed but raises without a desktop session. Telling someone
    to install what they already have sends them down a dead end."""
    import builtins

    real_import = builtins.__import__

    def refuse(name, *args, **kwargs):
        if name == "pynput":
            raise ImportError("this platform is not supported: no X connection")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", refuse)
    monkeypatch.delitem(doctor.sys.modules, "pynput", raising=False)

    state, detail = doctor._probe("pynput")

    assert state == "broken"
    assert "not supported" in detail

    result = doctor._package_result("pynput", "watching taps", "pynput", "pip install --user pynput")
    assert result.ok is False
    assert "installed, but will not load" in result.detail
    assert "pip install" not in result.remedy


def test_a_package_missing_one_of_its_own_dependencies_is_reported_as_broken(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def refuse(name, *args, **kwargs):
        if name == "pygetwindow":
            raise ImportError("No module named 'pyrect'", name="pyrect")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", refuse)
    monkeypatch.delitem(doctor.sys.modules, "pygetwindow", raising=False)

    state, detail = doctor._probe("pygetwindow")

    assert state == "broken"
    assert "pyrect" in detail
