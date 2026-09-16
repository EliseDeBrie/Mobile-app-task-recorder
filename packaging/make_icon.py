"""Draw the program's icon.

The executable had no icon, so Windows showed PyInstaller's own logo - a
feather - which says nothing about what the program is and looks like someone
forgot. This draws one: the handheld, and the red dot that means recording.

Run it after changing the design; the result is committed, so a build needs
nothing but the .ico file.

    python packaging/make_icon.py
"""

import os

from PIL import Image, ImageDraw

NAVY = (31, 56, 100, 255)      # the launcher's banner colour
SCREEN = (233, 238, 247, 255)
RED = (200, 42, 42, 255)
WHITE = (255, 255, 255, 255)

#: Windows picks the size it needs from these. 16 is the one that has to work:
#: it is the taskbar and the title bar, and it is where detail turns to mud.
SIZES = (256, 128, 64, 48, 32, 16)


def draw(size: int) -> Image.Image:
    """One square of the icon, drawn for the size it will be seen at."""
    scale = 8  # draw large and shrink, so the edges come out smooth
    box = size * scale
    image = Image.new("RGBA", (box, box), (0, 0, 0, 0))
    pen = ImageDraw.Draw(image)

    radius = box * 0.22
    pen.rounded_rectangle((0, 0, box - 1, box - 1), radius=radius, fill=NAVY)

    # The handheld: a tall rounded body with a lit screen in it. Below 32px
    # these details are smaller than a pixel, so the icon becomes the device
    # shape and the dot alone.
    detailed = size >= 32
    body = (box * 0.29, box * 0.13, box * 0.71, box * 0.87)
    pen.rounded_rectangle(body, radius=box * 0.08, fill=WHITE)

    if detailed:
        pen.rounded_rectangle(
            (box * 0.35, box * 0.20, box * 0.65, box * 0.55),
            radius=box * 0.03, fill=SCREEN,
        )
        for i in range(3):
            y = box * (0.245 + i * 0.09)
            pen.rounded_rectangle(
                (box * 0.39, y, box * 0.61, y + box * 0.045),
                radius=box * 0.02, fill=NAVY,
            )

    # The record dot, big enough to survive being shrunk to 16 pixels.
    dot = box * (0.11 if detailed else 0.15)
    centre = (box * 0.5, box * 0.70 if detailed else box * 0.62)
    pen.ellipse(
        (centre[0] - dot, centre[1] - dot, centre[0] + dot, centre[1] + dot),
        fill=RED,
    )

    return image.resize((size, size), Image.LANCZOS)


def main() -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    frames = [draw(size) for size in SIZES]

    ico = os.path.join(here, "whs-recorder.ico")
    frames[0].save(ico, format="ICO", sizes=[(s, s) for s in SIZES])

    # The same picture for the Tk windows, which want a PNG rather than an
    # .ico. It lives inside the package so that every way of installing the
    # tool carries it, not just the packaged executable.
    png = os.path.join(os.path.dirname(here), "src", "whs_recorder", "icon.png")
    draw(256).save(png, format="PNG")

    print(f"Wrote {ico} and {png}")


if __name__ == "__main__":
    main()
