"""The screen where a recording is corrected before it becomes a document.

Recording no longer interrupts to ask what each tap was; it writes down what it
read off the screen and moves on. That trade only works if the wording is easy
to fix afterwards, which is what this is: every step in a list, the screenshot
of the one you picked beside it, and the words in boxes you can edit.

Steps can also be dropped or moved. Recording by watching for changes catches
things nobody wants in a guide - a tooltip, a clock, a stray click - and
throwing those away here is quicker than trying not to make them.

Edits are kept as soon as you pick another step, so the list can be worked down
without pressing anything between steps. Nothing touches the file on disk until
Save.

Opened from the launcher, the document follows the recording: every Save
remakes it, and closing the window makes it once more and opens it. The window
itself never builds anything; it reports, and the launcher does the building.
"""

import os
from typing import Callable, Optional

from .branding import apply_icon
from .dialogs import collect_windows
from .instructions import ACTION_CHOICES, ACTION_LABELS, PREFERRED
from .recording import (
    INFO,
    SUBTASK_START,
    InfoStep,
    Recording,
    Step,
    SubtaskStart,
)

#: Fields on a Step that the right-hand pane edits, and what they are called.
STEP_FIELDS = (
    ("screen", "Screen"),
    ("control", "Button or field"),
    ("value", "Value typed or scanned"),
    ("title", "Note before the step"),
    ("note", "Note after the step"),
)

#: A section heading and an info step each hold one piece of text, and it goes
#: in the title box. What that box is called depends on which one you picked.
TITLE_LABELS = {
    SUBTASK_START: "Name of this section",
    INFO: "What this step tells the reader to do",
}

THUMBNAIL_WIDTH = 300
THUMBNAIL_HEIGHT = 500


def describe(node, number: Optional[int]) -> str:
    """One line for the list on the left."""
    if isinstance(node, SubtaskStart):
        return f"     [ {node.name or 'Section'} ]"

    lead = f"{number:>3}. " if number else "     "
    if isinstance(node, InfoStep):
        return f"{lead}{node.text or '(empty note)'}"
    if isinstance(node, Step):
        mark = "   - left out" if node.hidden or node.is_loading else ""
        return f"{lead}{node.instruction(PREFERRED)}{mark}"
    return "     [ end of section ]"


def lines(recording: Recording):
    """The list as it is shown: one line per node, numbered like the guide.

    A step that is left out keeps its place in the list - it has to, or it could
    not be put back - but it does not take a number, so the numbers match the
    document that will be built.
    """
    number = 0
    out = []
    for node in recording.nodes:
        countable = isinstance(node, (Step, InfoStep)) and not (
            node.hidden or getattr(node, "is_loading", False)
        )
        if countable:
            number += 1
        out.append(describe(node, number if countable else None))
    return out


class Review:
    """A window for correcting a recording."""

    def __init__(
        self,
        path: str,
        on_saved: Optional[Callable[[str], None]] = None,
        on_closed: Optional[Callable[[str], None]] = None,
    ):
        import tkinter as tk
        from tkinter import ttk

        self.tk, self.ttk = tk, ttk
        self.path = path
        self.recording = Recording.load(path)
        self.on_saved = on_saved
        self.on_closed = on_closed
        self.selected = -1
        self.dirty = False
        self.photo = None  # Tk drops an image that nothing holds on to
        self._filling = False  # suppress selection events while the list is rebuilt

        # Opened from the launcher there is already a root, and a second one in
        # the same process is the hazard that makes a window render but never
        # answer. Opened on its own, this is the root.
        self.owns_root = tk._default_root is None
        self.root = tk.Tk() if self.owns_root else tk.Toplevel()
        self.root.title(f"Check the steps - {self.recording.name}")
        apply_icon(self.root)
        self.root.geometry("1200x760")
        self.root.minsize(1000, 620)

        self._build_widgets()
        self._refresh(keep=0 if self.recording.nodes else None)

    # ----------------------------------------------------------------- widgets

    def _build_widgets(self) -> None:
        tk, ttk = self.tk, self.ttk
        family = "Segoe UI" if os.name == "nt" else "DejaVu Sans"
        mono = "Consolas" if os.name == "nt" else "monospace"

        header = ttk.Frame(self.root, padding=(16, 14, 16, 6))
        header.pack(fill="x")
        ttk.Label(header, text=self.recording.name, font=(family, 15, "bold")).pack(anchor="w")
        ttk.Label(
            header,
            text="Every step that was recorded is listed below. Pick one to see its "
                 "screenshot and correct the wording; anything that does not belong in "
                 "the guide can be left out or deleted.",
            foreground="#555", wraplength=930, justify="left", font=(family, 9),
        ).pack(anchor="w", pady=(3, 0))

        # The footer is claimed before the rest, so the buttons keep their strip
        # at the bottom whatever the pane above them asks for. A form taller
        # than the window otherwise pushes them off the screen entirely.
        footer = ttk.Frame(self.root, padding=(16, 10))
        footer.pack(side="bottom", fill="x")

        body = ttk.Frame(self.root, padding=(16, 6))
        body.pack(fill="both", expand=True)

        # Three columns: the steps, the boxes for the step you picked, and its
        # screenshot. Keeping the screenshot in a column of its own means a tall
        # one does not push the boxes down out of sight.
        shot = ttk.Frame(body, width=THUMBNAIL_WIDTH + 16)
        shot.pack(side="right", fill="y", padx=(14, 0))
        shot.pack_propagate(False)
        self.preview = ttk.Label(
            shot, text="No screenshot", anchor="center", background="#ececec",
            foreground="#666", relief="solid", borderwidth=1, wraplength=THUMBNAIL_WIDTH - 20,
        )
        self.preview.pack(fill="both", expand=True)

        right = ttk.Frame(body, width=300)
        right.pack(side="right", fill="y", padx=(14, 0))
        right.pack_propagate(False)

        # ------------------------------------------------------------ the list
        left = ttk.Frame(body)
        left.pack(side="left", fill="both", expand=True)

        # Packed before the list, so the buttons keep their strip at the bottom
        # rather than being squeezed out by a list that wants every pixel.
        order = ttk.Frame(left)
        order.pack(side="bottom", fill="x", pady=(8, 0))
        ttk.Button(order, text="Move up", command=lambda: self._move(-1)).pack(side="left")
        ttk.Button(order, text="Move down", command=lambda: self._move(1)).pack(
            side="left", padx=(6, 0)
        )
        ttk.Button(order, text="Delete this step", command=self._delete).pack(side="left", padx=(6, 0))

        listing = ttk.Frame(left)
        listing.pack(side="top", fill="both", expand=True)
        self.listbox = tk.Listbox(
            listing, font=(mono, 10), activestyle="none", exportselection=False,
            highlightthickness=0, borderwidth=1, relief="solid",
        )
        scroll = ttk.Scrollbar(listing, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=scroll.set)
        self.listbox.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.listbox.bind("<<ListboxSelect>>", self._on_pick)

        # ----------------------------------------------------------- the step
        ttk.Label(right, text="What happened", font=(family, 9, "bold")).pack(anchor="w")
        self.action = tk.StringVar()
        self.action_box = ttk.Combobox(
            right, textvariable=self.action, state="readonly",
            values=[label for label, _ in ACTION_CHOICES],
        )
        self.action_box.pack(fill="x", pady=(0, 6))

        self.fields = {}
        self.entries = {}
        self.labels = {}
        for key, label in STEP_FIELDS:
            caption = ttk.Label(right, text=label, font=(family, 9, "bold"))
            caption.pack(anchor="w")
            variable = tk.StringVar()
            entry = ttk.Entry(right, textvariable=variable)
            entry.pack(fill="x", pady=(0, 6), ipady=2)
            self.fields[key] = variable
            self.entries[key] = entry
            self.labels[key] = caption

        self.skip = tk.BooleanVar()
        self.skip_box = ttk.Checkbutton(
            right, text="Leave this step out", variable=self.skip
        )
        self.skip_box.pack(anchor="w", pady=(4, 0))
        ttk.Label(
            right,
            text="Your changes are kept as you move down the list. "
                 "Press Save when you are done.",
            foreground="#666", wraplength=280, justify="left", font=(family, 8),
        ).pack(anchor="w", pady=(10, 0))

        # ---------------------------------------------------------- the footer
        ttk.Button(footer, text="Save", command=self._save_clicked).pack(side="left")
        ttk.Button(
            footer, text="Done" if self.on_closed is not None else "Close", command=self._close
        ).pack(side="right")

        self.status = tk.StringVar()
        ttk.Label(footer, textvariable=self.status, foreground="#555").pack(side="left", padx=(14, 0))
        if self.on_closed is not None:
            ttk.Label(
                footer,
                text="Press Done when the steps read right: the document is made and opened.",
                foreground="#555", font=(family, 9),
            ).pack(side="right", padx=(0, 14))

        self.root.protocol("WM_DELETE_WINDOW", self._close)

    # ------------------------------------------------------------------- state

    def _count(self) -> str:
        kept = [
            n for n in self.recording.nodes
            if isinstance(n, (Step, InfoStep)) and not (n.hidden or getattr(n, "is_loading", False))
        ]
        left_out = len(self.recording.steps) - len([n for n in kept if isinstance(n, Step)])
        text = f"{len(kept)} step" + ("" if len(kept) == 1 else "s") + " in the document"
        return text + (f", {left_out} left out." if left_out else ".")

    def _refresh(self, keep: Optional[int] = None) -> None:
        """Redraw the list, and select `keep` without treating it as a new pick."""
        self._filling = True
        try:
            self.listbox.delete(0, "end")
            for line in lines(self.recording):
                self.listbox.insert("end", line)

            if keep is not None and 0 <= keep < self.listbox.size():
                self.listbox.selection_clear(0, "end")
                self.listbox.selection_set(keep)
                self.listbox.see(keep)
        finally:
            self._filling = False

        self.status.set(self._count())
        if keep is not None and 0 <= keep < len(self.recording.nodes):
            self._show(keep)
        elif not self.recording.nodes:
            self.selected = -1
            self._clear_fields()
            self._show_screenshot(None)

    def _on_pick(self, _event=None) -> None:
        if self._filling:
            return
        picked = self.listbox.curselection()
        if not picked or picked[0] == self.selected:
            return

        self._commit()
        self._refresh(keep=picked[0])

    def _clear_fields(self) -> None:
        """Empty the boxes. The screenshot has one owner, `_show_screenshot`."""
        for variable in self.fields.values():
            variable.set("")
        self.action.set("")
        self.skip.set(False)

    def _show(self, index: int) -> None:
        self.selected = index
        node = self.recording.nodes[index]
        self._clear_fields()

        is_step = isinstance(node, Step)
        if is_step:
            for label, name in ACTION_CHOICES:
                if name == node.action:
                    self.action.set(label)
                    break
            for key, variable in self.fields.items():
                variable.set(getattr(node, key, ""))
            self.skip.set(bool(node.hidden or node.is_loading))
        elif isinstance(node, InfoStep):
            self.fields["title"].set(node.text)
            self.skip.set(bool(node.hidden))
        elif isinstance(node, SubtaskStart):
            self.fields["title"].set(node.name)
            self.skip.set(bool(node.hidden))

        # A section heading and a note have one piece of text between them, and
        # it goes in the title box under a caption that says what it is. The
        # boxes they have no use for are greyed out rather than left there to
        # be typed into and quietly ignored.
        title_key = None if is_step else TITLE_LABELS.get(getattr(node, "type", ""))
        self.labels["title"].configure(text=title_key or dict(STEP_FIELDS)["title"])

        self.action_box.configure(state="readonly" if is_step else "disabled")
        for key, entry in self.entries.items():
            usable = is_step or (key == "title" and title_key is not None)
            entry.configure(state="normal" if usable else "disabled")
        self.skip_box.configure(state="normal" if hasattr(node, "hidden") else "disabled")

        self._show_screenshot(node)

    def _show_screenshot(self, node) -> None:
        path = self.recording.image_path(getattr(node, "action_img", ""))
        if not path or not os.path.isfile(path):
            self.preview.configure(image="", text="No screenshot for this step")
            self.photo = None
            return

        try:
            self.photo = self._thumbnail(path)
            self.preview.configure(image=self.photo, text="")
        except Exception as exc:  # a missing or corrupt file must not close the window
            self.preview.configure(image="", text=f"Cannot show the screenshot:\n{exc}")
            self.photo = None

    def _thumbnail(self, path: str):
        """A screenshot scaled to fit beside the list, without extra libraries."""
        import base64

        import cv2

        from .utils import read_image

        image = read_image(path)
        if image is None:
            raise ValueError("the file could not be read")

        height, width = image.shape[:2]
        scale = min(THUMBNAIL_WIDTH / width, THUMBNAIL_HEIGHT / height, 1.0)
        if scale < 1.0:
            image = cv2.resize(
                image, (max(int(width * scale), 1), max(int(height * scale), 1)),
                interpolation=cv2.INTER_AREA,
            )

        ok, buffer = cv2.imencode(".png", image)
        if not ok:
            raise ValueError("the image could not be converted")
        return self.tk.PhotoImage(data=base64.b64encode(buffer.tobytes()))

    # ----------------------------------------------------------------- editing

    def _commit(self) -> None:
        """Write what is in the boxes back onto the step that is showing."""
        if not (0 <= self.selected < len(self.recording.nodes)):
            return

        node = self.recording.nodes[self.selected]
        before = dict(vars(node))
        leave_out = bool(self.skip.get())

        if isinstance(node, Step):
            node.action = ACTION_LABELS.get(self.action.get(), node.action)
            for key, variable in self.fields.items():
                setattr(node, key, variable.get().strip())
            # One box stands for two flags, "hidden" and "loading", so it is
            # only written back when it was actually changed: reading a step
            # that is left out must not count as editing it.
            if leave_out != bool(node.hidden or node.is_loading):
                node.hidden = leave_out
                if not leave_out:
                    # Keeping a step the recorder took for the app loading has
                    # to clear that flag too, or the step would still be
                    # dropped when the document is built.
                    node.is_loading = False
        elif isinstance(node, InfoStep):
            node.text = self.fields["title"].get().strip()
            node.hidden = leave_out
        elif isinstance(node, SubtaskStart):
            node.name = self.fields["title"].get().strip()
            node.hidden = leave_out

        if vars(node) != before:
            self.dirty = True

    def _move(self, offset: int) -> None:
        if not (0 <= self.selected < len(self.recording.nodes)):
            return
        self._commit()
        moved = self.recording.move(self.selected, offset)
        self.dirty = self.dirty or moved != self.selected
        self.selected = moved
        self._refresh(keep=self.selected)

    def _delete(self) -> None:
        if not (0 <= self.selected < len(self.recording.nodes)):
            return
        self.recording.remove(self.selected)
        self.dirty = True
        if not self.recording.nodes:
            self.selected = -1
            self._refresh()
            return
        self.selected = min(self.selected, len(self.recording.nodes) - 1)
        self._refresh(keep=self.selected)

    # ------------------------------------------------------------------ saving

    def save(self) -> str:
        self._commit()
        self.recording.save(self.path)
        self.dirty = False
        return self.path

    def _save_clicked(self) -> None:
        self.save()
        self.status.set(f"Saved. {self._count()}")
        if self.on_saved is not None:
            self.on_saved(self.path)

    def _close(self) -> None:
        """Closing the window asks about unsaved changes, rather than guessing.

        Saving silently would overwrite the recording of someone who only came
        to look; discarding silently would throw away an afternoon of wording.
        """
        self._commit()
        if self.dirty:
            from tkinter import messagebox

            answer = messagebox.askyesnocancel(
                "Save your changes?",
                "You have changed some steps. Save them before closing?",
                parent=self.root,
            )
            if answer is None:
                return
            if answer:
                self.save()
        self.root.destroy()
        # Freed here, on the window's own thread: left to the garbage
        # collector it would be freed on whichever thread ran it next, and Tk
        # aborts the process when that is not the thread that made the window.
        collect_windows()
        if self.on_closed is not None:
            self.on_closed(self.path)

    def run(self) -> None:
        if self.owns_root:
            self.root.mainloop()


def main(path: str) -> None:
    """Open the review window on its own, for `whs-recorder review`."""
    Review(path).run()
