# PyInstaller build: one file, no Python install needed on the machine.
#
# Built as a console application on purpose. The launcher hides that console
# the moment it opens a window, and keeping it means the commands the launcher
# runs for itself have somewhere to write, which is how their output reaches
# the log pane.

from PyInstaller.utils.hooks import collect_submodules

# These are reached through importlib at runtime, so nothing in the source
# tree names them and PyInstaller's analysis cannot see them by itself.
WINRT_MODULES = [
    "winrt.system",
    "winrt.windows.media.ocr",
    "winrt.windows.graphics.imaging",
    "winrt.windows.storage.streams",
    "winrt.windows.foundation",
    "winrt.windows.globalization",
    "winsdk.system",
    "winsdk.windows.media.ocr",
    "winsdk.windows.graphics.imaging",
    "winsdk.windows.storage.streams",
]

hidden = [
    # The launcher is imported only when the program starts with no arguments.
    "whs_recorder.app",
    "whs_recorder.cli",
    # pynput picks its backend at import time, by platform.
    *collect_submodules("pynput"),
]

for module in WINRT_MODULES:
    try:
        __import__(module)
    except ImportError:
        continue  # not installed in this build; OCR falls back or goes quiet
    hidden.append(module)

import os

analysis = Analysis(
    # Resolved against the spec's own folder, so the build works from anywhere.
    [os.path.join(SPECPATH, "entry.py")],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    # Nothing here needs a test runner or a plotting stack along for the ride.
    excludes=["pytest", "matplotlib", "tkinter.test", "test"],
    noarchive=False,
)

pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="WHS Task Recorder",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
)
