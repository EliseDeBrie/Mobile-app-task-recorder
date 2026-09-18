"""A small recording for the packaged program to build a document from.

The build on CI proves the executable starts and can read text, but a document
is what the program is for, and python-docx carries a template that has to be
packed in with it. This writes a two-step recording with a screenshot each, so
the workflow can ask the executable to turn it into a document and count the
pictures that came out.

    python packaging/smoke.py <folder>
"""

import os
import sys

import numpy as np

from whs_recorder.recording import Recording, Step
from whs_recorder.utils import write_image


def screenshot(folder: str, name: str, shade: int) -> str:
    frame = np.full((640, 360, 3), shade, dtype=np.uint8)
    frame[0:60, :] = (100, 60, 30)
    frame[200:240, 40:320] = (30, 30, 30)
    write_image(os.path.join(folder, "shots", name), frame)
    return os.path.join("shots", name)


def main(folder: str) -> str:
    os.makedirs(os.path.join(folder, "shots"), exist_ok=True)
    recording = Recording(name="Smoke test", description="Built by CI from the packaged program.")
    recording.add(Step(t=1.0, action="menu", control="Inbound", screen="Main menu",
                       action_img=screenshot(folder, "step1.png", 240)))
    recording.add(Step(t=2.0, action="scan", control="LP", value="LP000123", screen="Purchase receive",
                       action_img=screenshot(folder, "step2.png", 220)))
    path = recording.save(os.path.join(folder, "recording.json"))
    print(path)
    return path


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "smoke")
