"""What this machine can and cannot do, and how to fix it without an administrator.

Consultants work on customer machines where they are not administrators, so
every part of this tool is meant to install and run as a plain user. This is the
report that proves it, or names the one thing that is missing.
"""

import os
import sys
from dataclasses import dataclass
from typing import List

from . import ocr

#: Printed into a test image and read back, to prove the engine really works.
SELF_TEST_TEXT = "WHS RECORDER 12345"

MIN_PYTHON = (3, 10)

def _pip(package: str) -> str:
    return f"pip install --user {package}"


def _tkinter_remedy() -> str:
    if os.name == "nt":
        return "re-run the Python installer and tick 'tcl/tk and IDLE'; no administrator needed"
    return "install your distribution's python3-tk package"


#: (import name, what it is for, name to show, how to get it)
PACKAGES = [
    ("cv2", "reading and writing screenshots", "opencv-python", _pip("opencv-python")),
    ("numpy", "comparing frames", "numpy", _pip("numpy")),
    ("docx", "writing the Word document", "python-docx", _pip("python-docx")),
    ("mss", "capturing the screen", "mss", _pip("mss")),
    ("pynput", "watching for taps and keys", "pynput", _pip("pynput")),
    ("tkinter", "the region selector and the step popup", "tkinter", ""),
]

OPTIONAL_PACKAGES = [
    ("pygetwindow", "finding the app by window title", "pygetwindow", _pip("pygetwindow")),
]


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str = ""
    remedy: str = ""
    optional: bool = False


def _probe(module: str):
    """Whether a package can be used here: ("ok" | "missing" | "broken", detail).

    A package that is installed but refuses to load is a different problem from
    one that was never installed, and telling someone to install what they
    already have sends them down a dead end. pynput, for one, raises an
    ImportError when there is no desktop session, though it is sitting right
    there.
    """
    try:
        __import__(module)
        return "ok", ""
    except ImportError as exc:
        detail = str(exc).strip().splitlines()[0]
        missing = getattr(exc, "name", None)
        if missing is None or missing == module or missing.startswith(f"{module}."):
            if missing is None and detail and module not in detail:
                # An ImportError with no module name, raised by the package
                # itself: it is installed, and unhappy about something else.
                return "broken", detail
            return "missing", detail
        return "broken", f"{detail} (it needs {missing})"
    except Exception as exc:
        return "broken", str(exc).strip().splitlines()[0]


def check_python() -> CheckResult:
    version = ".".join(str(p) for p in sys.version_info[:3])
    if sys.version_info[:2] < MIN_PYTHON:
        return CheckResult(
            "Python", False, f"{version} is too old",
            f"install Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or later for your user only "
            "(clear 'Install for all users', or use the Store build)",
        )

    if os.name != "nt":
        return CheckResult("Python", True, version)

    prefix = (sys.prefix or "").lower()
    if "windowsapps" in prefix:
        where = "installed from the Store, for this user"
    elif "program files" in prefix:
        where = "installed for all users, which took an administrator once"
    else:
        where = "installed for this user"
    return CheckResult("Python", True, f"{version}, {where}")


def check_packages() -> List[CheckResult]:
    results = []
    for module, purpose, name, remedy in PACKAGES:
        if module == "tkinter":
            remedy = _tkinter_remedy()
        results.append(_package_result(module, purpose, name, remedy))
    for module, purpose, name, remedy in OPTIONAL_PACKAGES:
        result = _package_result(module, purpose, name, remedy, optional=True)
        results.append(result)
    return results


def _package_result(module, purpose, name, remedy, optional=False) -> CheckResult:
    state, detail = _probe(module)

    if state == "ok":
        return CheckResult(name, True, purpose, optional=optional)
    if state == "broken":
        return CheckResult(
            name, False, f"installed, but will not load: {detail}",
            "it is already installed, so this is the environment rather than a missing package",
            optional=optional,
        )

    prefix = "not installed; only needed for" if optional else "missing, needed for"
    return CheckResult(name, False, f"{prefix} {purpose}", remedy, optional=optional)


def check_screen() -> CheckResult:
    """Can this process actually photograph the screen?"""
    try:
        from .region import open_capture

        with open_capture() as capture:
            bounds = capture.monitors[0]
        return CheckResult(
            "Screen capture", True,
            f"{bounds['width']}x{bounds['height']} desktop, {len(capture.monitors) - 1} monitor(s)",
        )
    except Exception as exc:
        return CheckResult(
            "Screen capture", False, f"failed ({exc})",
            "check that a desktop session is available; no administrator rights are needed",
        )


def check_ocr() -> List[CheckResult]:
    """Report the OCR engines, without nagging about one that is not needed.

    Two engines can do this job and one is plenty. Listing the spare one with
    instructions to install it reads like a problem to fix, when the only thing
    that matters is whether some engine works.
    """
    results = []
    active = ocr.active_backend()

    for status in ocr.statuses():
        if status.ready and status.name == active:
            results.append(
                CheckResult(f"OCR: {status.name}", True, f"{status.detail} - in use", optional=True)
            )
            continue

        if active:
            # Something else is doing the reading, so this one is spare.
            results.append(
                CheckResult(
                    f"OCR: {status.name}", True,
                    f"not needed, {active} is doing the reading", optional=True,
                )
            )
            continue

        results.append(
            CheckResult(f"OCR: {status.name}", status.ready, status.detail, status.remedy, optional=True)
        )

    if not active:
        results.append(
            CheckResult(
                "OCR", False,
                "no engine, so the popup will not fill itself in",
                "everything else still works; the fields are typed by hand",
                optional=True,
            )
        )
    return results


def selftest_image():
    """A plain black-on-white line, of the kind a handheld screen shows."""
    import cv2
    import numpy as np

    image = np.full((120, 720, 3), 245, dtype=np.uint8)
    cv2.putText(image, SELF_TEST_TEXT, (20, 82), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (20, 20, 20), 3,
                cv2.LINE_AA)
    return image


def check_ocr_reads() -> CheckResult:
    """Actually read something, rather than trusting that the engine loads.

    On Windows this is the moment the built-in engine is proven, which is worth
    doing here rather than discovering it mid-recording.
    """
    engine = ocr.active_backend()
    if not engine:
        return CheckResult(
            "OCR: reading a test image", False, "skipped, no engine",
            "the popup will simply open blank", optional=True,
        )

    try:
        lines = ocr.read_lines(selftest_image())
    except Exception as exc:
        return CheckResult(
            f"OCR: reading a test image with {engine}", False, f"failed ({exc})",
            "record with --no-suggest, or switch engines with --ocr", optional=True,
        )

    read_back = " ".join(line.text for line in lines).upper()
    found = [part for part in SELF_TEST_TEXT.split() if part in read_back]

    if len(found) >= 2:
        return CheckResult(f"OCR: reading a test image with {engine}", True, f'read "{read_back}"')

    # The reader swallows engine failures so a recording survives them, so ask
    # why it came back empty rather than calling a broken engine a poor reader.
    failure = ocr.last_error()
    if failure:
        return CheckResult(
            f"OCR: reading a test image with {engine}", False,
            f"the engine failed: {failure}",
            "record with --no-suggest, or switch engines with --ocr", optional=True,
        )

    return CheckResult(
        f"OCR: reading a test image with {engine}", False,
        f'read "{read_back}" instead of "{SELF_TEST_TEXT}"',
        "the engine loads but reads poorly; try the other engine with --ocr", optional=True,
    )


def run_checks() -> List[CheckResult]:
    results = [check_python()]
    results.extend(check_packages())
    results.append(check_screen())
    results.extend(check_ocr())
    results.append(check_ocr_reads())
    return results


def report(results: List[CheckResult]) -> str:
    """Render the checks, with what to do about anything missing."""
    lines = []
    for result in results:
        mark = "ok  " if result.ok else ("--  " if result.optional else "MISSING")
        lines.append(f"{mark} {result.name}: {result.detail}".rstrip(": "))
        if not result.ok and result.remedy:
            lines.append(f"       {result.remedy}")

    required_missing = [r for r in results if not r.ok and not r.optional]
    lines.append("")
    if required_missing:
        lines.append(f"{len(required_missing)} required item(s) missing, listed above.")
    else:
        lines.append("Everything needed to record and build is present.")
    lines.append("None of it needs administrator rights.")
    return "\n".join(lines)
