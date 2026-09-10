"""The recording model, shaped like a D365 Task Recorder recording.

A Task Recorder recording is a name, a description and an ordered list of nodes.
Most nodes are user-action steps; the rest give the recording structure:

* **Subtask start / end** group a run of steps and may nest, purely to make a
  long process readable.
* **Info steps** are numbered steps whose text the author writes, for actions
  that happen away from the device.
* **Hidden** steps stay in the recording but are left out of the guide.

Each step also carries the two annotations Task Recorder supports: a *title*
shown above the generated instruction, and a *note* shown after it.

This module reads and writes that model as JSON, and still loads the flat
`{"markers": [...]}` files written before v0.3.
"""

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional, Union

from .instructions import PREFERRED, render_instruction
from .region import Region
from .utils import ensure_parent_dir

FORMAT = "whs-task-recording"
FORMAT_VERSION = 3

STEP = "step"
INFO = "info"
SUBTASK_START = "subtask_start"
SUBTASK_END = "subtask_end"


@dataclass
class Step:
    """A recorded user action."""

    t: float = 0.0
    action: str = "tap"
    control: str = ""
    value: str = ""
    #: The screen the step happened on, which groups steps the way a form does.
    screen: str = ""
    title: str = ""
    note: str = ""
    user_text: str = ""
    instruction_label: Optional[str] = None
    hidden: bool = False
    is_loading: bool = False
    reason: str = ""
    diff: float = 0.0

    #: Screenshots captured while recording, relative to the recording file.
    action_img: str = ""
    result_img: str = ""
    result_toast: str = ""

    type: str = STEP

    def instruction(self, value_mode: str = PREFERRED) -> str:
        return render_instruction(
            self.action,
            control=self.control,
            value=self.value,
            value_mode=value_mode,
            user_text=self.user_text,
            instruction_label=self.instruction_label,
        )


@dataclass
class InfoStep:
    """A numbered step the author wrote, with no recorded action behind it."""

    t: float = 0.0
    text: str = ""
    title: str = ""
    note: str = ""
    hidden: bool = False

    type: str = INFO

    def instruction(self, value_mode: str = PREFERRED) -> str:
        text = " ".join((self.text or "").split())
        if text and text[-1] not in ".!?:":
            text += "."
        return text


@dataclass
class SubtaskStart:
    """The beginning of a group of steps."""

    t: float = 0.0
    name: str = ""
    hidden: bool = False

    type: str = SUBTASK_START


@dataclass
class SubtaskEnd:
    """The end of the innermost open group."""

    t: float = 0.0

    type: str = SUBTASK_END


Node = Union[Step, InfoStep, SubtaskStart, SubtaskEnd]

_NODE_TYPES = {STEP: Step, INFO: InfoStep, SUBTASK_START: SubtaskStart, SUBTASK_END: SubtaskEnd}


@dataclass
class OutlineEntry:
    """One line of the guide: a step, an info step, or a subtask heading."""

    kind: str
    node: Node
    depth: int = 0
    number: Optional[int] = None
    node_index: int = -1


@dataclass
class Recording:
    name: str = "Untitled recording"
    description: str = ""
    start_epoch: float = 0.0
    monitor_index: int = 1
    diff_threshold: float = 7.5
    region: Optional[Region] = None
    nodes: List[Node] = field(default_factory=list)

    #: Where the file was read from or written to. Not part of the JSON.
    source_path: str = ""

    def image_path(self, relative: str) -> str:
        """Resolve a screenshot path recorded relative to the recording file."""
        if not relative:
            return ""
        if os.path.isabs(relative) or not self.source_path:
            return relative
        return os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(self.source_path)), relative))

    @property
    def has_screenshots(self) -> bool:
        return any(step.action_img for step in self.steps)

    # ------------------------------------------------------------------ nodes

    def add(self, node: Node) -> Node:
        self.nodes.append(node)
        return node

    @property
    def steps(self) -> List[Step]:
        return [n for n in self.nodes if isinstance(n, Step)]

    def open_subtasks(self) -> int:
        """How many subtasks are still open, so the recorder can end them."""
        depth = 0
        for node in self.nodes:
            if isinstance(node, SubtaskStart):
                depth += 1
            elif isinstance(node, SubtaskEnd) and depth:
                depth -= 1
        return depth

    def outline(self, skip_loading: bool = True, include_hidden: bool = False) -> List[OutlineEntry]:
        """Flatten the recording into numbered guide lines.

        Numbering runs continuously across subtasks, as it does in Task
        Recorder. Hidden steps, and loading steps when `skip_loading` is set,
        are left out and do not take a number.
        """
        entries: List[OutlineEntry] = []
        depth = 0
        number = 0

        for index, node in enumerate(self.nodes):
            if isinstance(node, SubtaskEnd):
                depth = max(depth - 1, 0)
                continue

            if isinstance(node, SubtaskStart):
                if not node.hidden or include_hidden:
                    entries.append(OutlineEntry(SUBTASK_START, node, depth, None, index))
                depth += 1
                continue

            if node.hidden and not include_hidden:
                continue
            if skip_loading and isinstance(node, Step) and node.is_loading:
                continue

            number += 1
            entries.append(OutlineEntry(node.type, node, depth, number, index))

        return entries

    # ------------------------------------------------------------------- json

    def to_dict(self) -> Dict[str, Any]:
        return {
            "format": FORMAT,
            "version": FORMAT_VERSION,
            "name": self.name,
            "description": self.description,
            "start_epoch": self.start_epoch,
            "monitor_index": self.monitor_index,
            "diff_threshold": self.diff_threshold,
            "region": self.region.to_dict() if self.region else None,
            "nodes": [_node_to_dict(n) for n in self.nodes],
        }

    def save(self, path: str) -> str:
        ensure_parent_dir(path)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
        self.source_path = path
        return path

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "Recording":
        if "nodes" not in data and "markers" in data:
            return _from_legacy_markers(data)

        recording = Recording(
            name=data.get("name") or "Untitled recording",
            description=data.get("description", ""),
            start_epoch=float(data.get("start_epoch", 0.0)),
            monitor_index=int(data.get("monitor_index", 1)),
            diff_threshold=float(data.get("diff_threshold", 7.5)),
            region=Region.from_dict(data.get("region")),
        )
        recording.nodes = [_node_from_dict(n) for n in data.get("nodes", [])]
        return recording

    @staticmethod
    def load(path: str) -> "Recording":
        with open(path, "r", encoding="utf-8") as f:
            recording = Recording.from_dict(json.load(f))
        recording.source_path = path
        return recording


def _node_to_dict(node: Node) -> Dict[str, Any]:
    data = {"type": node.type}
    for key, value in vars(node).items():
        if key != "type":
            data[key] = value
    return data


def _node_from_dict(data: Dict[str, Any]) -> Node:
    node_type = data.get("type", STEP)
    cls = _NODE_TYPES.get(node_type, Step)
    fields = {k: v for k, v in data.items() if k in cls.__dataclass_fields__ and k != "type"}
    return cls(**fields)


def _from_legacy_markers(data: Dict[str, Any]) -> Recording:
    """Load a pre-v0.3 markers file.

    Those files hold one free-text title per marker, which was the whole step
    sentence. That maps onto a user-supplied instruction, so documents built
    from an old file read exactly as they did before.
    """
    recording = Recording(
        name=data.get("name") or "Untitled recording",
        description=data.get("description", ""),
        start_epoch=float(data.get("start_epoch", 0.0)),
        monitor_index=int(data.get("monitor_index", 1)),
        diff_threshold=float(data.get("diff_threshold", 7.5)),
    )

    for marker in data.get("markers", []):
        recording.add(
            Step(
                t=float(marker.get("t", 0.0)),
                action="tap",
                user_text=(marker.get("title") or "").strip(),
                note=(marker.get("notes") or "").strip(),
                is_loading=bool(marker.get("is_loading")),
                reason=marker.get("reason", ""),
                diff=float(marker.get("diff", 0.0)),
            )
        )

    return recording


def iter_steps(recording: Recording) -> Iterator[Step]:
    for node in recording.nodes:
        if isinstance(node, Step):
            yield node
