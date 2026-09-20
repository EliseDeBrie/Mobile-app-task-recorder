# PyInstaller build: no Python install needed on the machine.
#
# Built as a windowed application: double-clicking it opens the launcher with
# no console at all. Run as a command it attaches to the terminal it was
# started from, and the commands the launcher runs for itself are handed pipes,
# so their output still reaches the log pane.
#
# Two shapes come out of the same spec:
#
#   pyinstaller packaging/whs-recorder.spec
#       One file, "dist/WHS Task Recorder.exe", for the Releases page. It
#       unpacks itself into a temporary folder each time it starts.
#
#   WHS_BUILD=folder pyinstaller packaging/whs-recorder.spec
#       One folder, "dist/WHS Task Recorder/", with the program and its
#       libraries laid out as files. This is what the MSIX package is made
#       from (see make_msix.py): an installed app runs from where it was
#       installed and unpacks nothing.

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
    # The window icon travels with the program: Windows takes the title-bar
    # and taskbar icon from the .ico below, but Tk sets its own per window and
    # wants a PNG.
    datas=[(os.path.join(SPECPATH, os.pardir, "src", "whs_recorder", "icon.png"),
             "whs_recorder")],
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    # Nothing here needs a test runner or a plotting stack along for the ride.
    excludes=["pytest", "matplotlib", "tkinter.test", "test"],
    noarchive=False,
)

pyz = PYZ(analysis.pure)

as_folder = os.environ.get("WHS_BUILD", "").lower() == "folder"

exe_options = dict(
    name="WHS Task Recorder",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # Windowed: double-clicking opens the launcher and never a console.
    # Run as a command, it attaches to the terminal it was started from.
    console=False,
    disable_windowed_traceback=False,
    # Without this Windows falls back to PyInstaller's own logo, which is a
    # feather and tells a user nothing about what they just downloaded.
    icon=os.path.join(SPECPATH, "whs-recorder.ico"),
)

if as_folder:
    exe = EXE(
        pyz,
        analysis.scripts,
        [],
        exclude_binaries=True,
        **exe_options,
    )
    COLLECT(
        exe,
        analysis.binaries,
        analysis.datas,
        strip=False,
        upx=False,
        name="WHS Task Recorder",
    )
else:
    exe = EXE(
        pyz,
        analysis.scripts,
        analysis.binaries,
        analysis.datas,
        [],
        runtime_tmpdir=None,
        **exe_options,
    )
