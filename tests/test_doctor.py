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
