"""The program's own icon, on every window it opens.

Without this the executable carried PyInstaller's logo - a feather - and the
windows carried Tk's, neither of which says anything about what the program is.
The executable's icon is set in the build spec; this is the other half, for the
windows themselves.

Failing to find the picture is never worth interrupting anyone over: a window
with the wrong icon still records a process.
"""

import os
import sys
from typing import Optional

ICON_FILE = "icon.png"


def icon_path() -> Optional[str]:
    """Where the icon is, from a checkout or from inside the packaged program."""
    here = os.path.dirname(os.path.abspath(__file__))

    # PyInstaller unpacks the bundled files to a temporary folder and points
    # sys._MEIPASS at it; the package's own folder is elsewhere in the bundle.
    bundle = getattr(sys, "_MEIPASS", "")
    candidates = [os.path.join(here, ICON_FILE)]
    if bundle:
        candidates.insert(0, os.path.join(bundle, "whs_recorder", ICON_FILE))

    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return None


def apply_icon(window) -> bool:
    """Put the program's icon on `window`. Says whether it managed it."""
    path = icon_path()
    if not path:
        return False

    try:
        import tkinter as tk

        photo = tk.PhotoImage(file=path)
        # Held on the window: Tk drops an image nothing refers to, and the
        # icon would go blank the moment this function returned.
        window._whs_icon = photo
        window.iconphoto(True, photo)
        return True
    except Exception:
        return False
