"""Choosing the part of the screen the warehouse app occupies.

The WHS mobile app runs as a window on the PC, so there is no browser tab to
hand to an extension and no point capturing the whole monitor: the taskbar, the
clock and a second screen would all land in the guide, and a blinking clock
would trigger steps of its own.

A region can be chosen three ways:

* **Drag it** - a dimmed full-screen overlay you drag a rectangle on, the way
  Greenshot and PowerPoint's screen clipping work.
* **Name a window** - resolved by title when `pygetwindow` is installed, which
  keeps working if the window is moved between sessions.
* **Type it** - ``x,y,width,height``, for scripting a fixed kiosk layout.
"""

import contextlib
import os
import re
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

MIN_SIDE = 8  # a smaller drag is a stray click, not a selection


@dataclass
class Region:
    """A rectangle in virtual-desktop coordinates."""

    left: int
    top: int
    width: int
    height: int
    source: str = "manual"

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height

    def to_monitor(self) -> Dict[str, int]:
        """The dict shape `mss` grabs."""
        return {"left": self.left, "top": self.top, "width": self.width, "height": self.height}

    def crop(self, frame):
        """Cut this region out of a full-screen frame, clamped to the frame."""
        if frame is None:
            return None
        height, width = frame.shape[:2]
        left = max(min(self.left, width), 0)
        top = max(min(self.top, height), 0)
        right = max(min(self.right, width), left)
        bottom = max(min(self.bottom, height), top)
        if right - left < 1 or bottom - top < 1:
            return frame
        return frame[top:bottom, left:right]

    def to_dict(self) -> Dict[str, object]:
        return {
            "left": self.left,
            "top": self.top,
            "width": self.width,
            "height": self.height,
            "source": self.source,
        }

    @staticmethod
    def from_dict(data: Optional[Dict[str, object]]) -> Optional["Region"]:
        if not data:
            return None
        return Region(
            left=int(data.get("left", 0)),
            top=int(data.get("top", 0)),
            width=int(data.get("width", 0)),
            height=int(data.get("height", 0)),
            source=str(data.get("source", "manual")),
        )

    def describe(self) -> str:
        return f"{self.width}x{self.height} at {self.left},{self.top} ({self.source})"


def normalise_box(x1: int, y1: int, x2: int, y2: int, source: str = "manual") -> Optional[Region]:
    """Turn two dragged corners into a region, in any drag direction."""
    left, right = sorted((int(x1), int(x2)))
    top, bottom = sorted((int(y1), int(y2)))
    width, height = right - left, bottom - top
    if width < MIN_SIDE or height < MIN_SIDE:
        return None
    return Region(left, top, width, height, source)


def parse_region(text: str) -> Optional[Region]:
    """Parse `x,y,width,height`, or return None for 'full' and empty input."""
    text = (text or "").strip()
    if not text or text.lower() == "full":
        return None

    parts = [p for p in re.split(r"[,\sx]+", text) if p]
    if len(parts) != 4:
        raise ValueError(f"Cannot read region {text!r}: expected x,y,width,height")
    try:
        left, top, width, height = (int(p) for p in parts)
    except ValueError as exc:
        raise ValueError(f"Cannot read region {text!r}: expected four whole numbers") from exc
    if width < MIN_SIDE or height < MIN_SIDE:
        raise ValueError(f"Region {text!r} is too small to capture")
    return Region(left, top, width, height, "manual")


def popup_position(
    region: Optional[Region],
    screen: Tuple[int, int, int, int],
    popup_size: Tuple[int, int] = (420, 640),
    gap: int = 12,
) -> Tuple[int, int]:
    """Where to put the step popup so it does not cover the app.

    The popup is captured too if it overlaps the region, so it is placed beside
    the region: to its right, else to its left, else below, else above. When
    nothing fits it goes in the screen corner furthest from the region.
    """
    screen_left, screen_top, screen_width, screen_height = screen
    popup_width, popup_height = popup_size
    screen_right = screen_left + screen_width
    screen_bottom = screen_top + screen_height

    if region is None:
        return screen_left + gap, screen_top + gap

    top = min(max(region.top, screen_top), max(screen_bottom - popup_height, screen_top))
    left = min(max(region.left, screen_left), max(screen_right - popup_width, screen_left))

    if region.right + gap + popup_width <= screen_right:
        return region.right + gap, top
    if region.left - gap - popup_width >= screen_left:
        return region.left - gap - popup_width, top
    if region.bottom + gap + popup_height <= screen_bottom:
        return left, region.bottom + gap
    if region.top - gap - popup_height >= screen_top:
        return left, region.top - gap - popup_height

    # Nothing fits beside it: use the corner furthest from the region's centre.
    centre_x = region.left + region.width / 2
    centre_y = region.top + region.height / 2
    x = screen_left + gap if centre_x > screen_left + screen_width / 2 else max(screen_right - popup_width - gap, screen_left)
    y = screen_top + gap if centre_y > screen_top + screen_height / 2 else max(screen_bottom - popup_height - gap, screen_top)
    return x, y


def use_physical_pixels() -> None:
    """On Windows, have this process see the screen in physical pixels.

    The capture library works in physical pixels. Tk, in a process that has
    not declared it understands display scaling, is handed logical ones and
    scaled up by Windows: on a 125% display the box dragged over the app comes
    back a quarter too small and too far up and left, and every screenshot is
    of the wrong part of the screen. Declaring awareness makes Tk report the
    same pixels the capture uses.

    Only the recorder calls this, and it runs as a process of its own: the
    launcher window is better off scaled by Windows, and is.
    """
    if os.name != "nt":
        return
    try:
        import ctypes

        try:
            # Per-monitor awareness: right on every screen of a mixed setup.
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except (AttributeError, OSError):
            ctypes.windll.user32.SetProcessDPIAware()  # Windows before 8.1
    except Exception:
        pass  # already declared, or an unexpected Windows: capture as before


def open_capture():
    """Open a screen-capture session, across mss versions.

    mss 10 renamed the entry point to `MSS` and deprecated the old lowercase
    alias, so ask for whichever this install has.
    """
    import mss

    factory = getattr(mss, "MSS", None) or mss.mss
    return factory()


def virtual_screen() -> Tuple[int, int, int, int]:
    """Bounds of the whole desktop, across every monitor."""
    with open_capture() as sct:
        bounds = sct.monitors[0]
    return bounds["left"], bounds["top"], bounds["width"], bounds["height"]


def _dimmed_screen_photo(tk_module, dim: float = 0.45):
    """The desktop as it looks right now, darkened, for the overlay to sit on.

    A translucent window only looks translucent where a compositor is running,
    and there is not always one. Painting a darkened screenshot instead works
    everywhere, and is what Greenshot does.
    """
    import base64

    import cv2
    import numpy as np

    with open_capture() as sct:
        shot = np.array(sct.grab(sct.monitors[0]))[:, :, :3]

    darkened = (shot.astype(np.float32) * dim).astype(np.uint8)
    ok, buffer = cv2.imencode(".png", darkened)
    if not ok:
        return None
    return tk_module.PhotoImage(data=base64.b64encode(buffer.tobytes()))


def region_from_window(title: str) -> Optional[Region]:
    """Find a window by a part of its title. Needs `pygetwindow`."""
    try:
        import pygetwindow
    except ImportError as exc:
        raise RuntimeError(
            "Selecting a window by title needs pygetwindow: pip install --user pygetwindow"
        ) from exc

    wanted = (title or "").strip().lower()
    matches = [
        w for w in pygetwindow.getAllWindows()
        if wanted in (w.title or "").lower() and w.width > MIN_SIDE and w.height > MIN_SIDE
    ]
    if not matches:
        return None

    window = matches[0]
    return Region(int(window.left), int(window.top), int(window.width), int(window.height),
                  f"window:{window.title}")


def select_region(parent=None) -> Optional[Region]:
    """Drag a rectangle over a dimmed screen. Escape cancels.

    With a `parent` root the overlay is a Toplevel on that root's thread, which
    is how the recorder opens it; without one it makes a root of its own.
    """
    import tkinter as tk

    left, top, width, height = virtual_screen()
    chosen = [None]

    standalone = parent is None
    root = tk.Tk() if standalone else tk.Toplevel(parent)
    root.overrideredirect(True)
    root.geometry(f"{width}x{height}+{left}+{top}")
    root.attributes("-topmost", True)
    root.configure(bg="black")
    root.config(cursor="crosshair")

    canvas = tk.Canvas(root, bg="black", highlightthickness=0, cursor="crosshair")
    canvas.pack(fill="both", expand=True)

    try:
        backdrop = _dimmed_screen_photo(tk)
    except Exception:
        backdrop = None
    if backdrop is not None:
        canvas.create_image(0, 0, anchor="nw", image=backdrop)
        canvas.image = backdrop  # keep a reference, or Tk drops the picture
    else:
        # No screenshot available: fall back to a translucent window.
        with contextlib.suppress(tk.TclError):
            root.attributes("-alpha", 0.35)

    hint = canvas.create_text(
        width // 2, 40,
        text="Drag over the warehouse app window.  Escape cancels.",
        fill="white", font=("Segoe UI", 16),
    )
    box = canvas.create_rectangle(0, 0, 0, 0, outline="#00ff88", width=2)
    size_text = canvas.create_text(0, 0, text="", fill="#00ff88", font=("Segoe UI", 12), anchor="nw")
    start = {}

    def on_press(event):
        start["x"], start["y"] = event.x, event.y
        canvas.itemconfigure(hint, state="hidden")

    def on_drag(event):
        if "x" not in start:
            return
        canvas.coords(box, start["x"], start["y"], event.x, event.y)
        canvas.coords(size_text, min(start["x"], event.x), min(start["y"], event.y) - 22)
        canvas.itemconfigure(
            size_text, text=f"{abs(event.x - start['x'])} x {abs(event.y - start['y'])}"
        )

    def on_release(event):
        if "x" not in start:
            return
        picked = normalise_box(
            start["x"] + left, start["y"] + top, event.x + left, event.y + top, "select"
        )
        if picked is None:
            # A click rather than a drag. Ask again instead of cancelling the
            # whole recording over a slip of the mouse.
            start.clear()
            canvas.coords(box, 0, 0, 0, 0)
            canvas.itemconfigure(size_text, text="")
            canvas.itemconfigure(hint, state="normal")
            return
        chosen[0] = picked
        root.destroy()

    canvas.bind("<ButtonPress-1>", on_press)
    canvas.bind("<B1-Motion>", on_drag)
    canvas.bind("<ButtonRelease-1>", on_release)
    root.bind("<Escape>", lambda _e: root.destroy())
    root.focus_force()

    if standalone:
        root.mainloop()
    else:
        from .dialogs import wait_for

        wait_for(parent, root)
    return chosen[0]


def resolve_region(spec: Optional[str]) -> Optional[Region]:
    """Turn a `--region` value into a region.

    `select` opens the drag overlay, `window:<title>` looks a window up, `full`
    or nothing captures the whole monitor, anything else is `x,y,width,height`.
    """
    spec = (spec or "").strip()
    if not spec or spec.lower() == "full":
        return None
    if spec.lower() == "select":
        from .dialogs import collect_windows

        use_physical_pixels()
        try:
            return select_region()
        finally:
            # The overlay's canvas, picture and window refer to one another,
            # so it is the cyclic collector's to free - and that runs on
            # whichever thread next allocates. Free it here, on this one.
            collect_windows()
    if spec.lower().startswith("window:"):
        region = region_from_window(spec.split(":", 1)[1])
        if region is None:
            raise RuntimeError(f"No window matches {spec.split(':', 1)[1]!r}")
        return region
    return parse_region(spec)
