"""Step instruction text, generated the way D365 Task Recorder generates it.

Task Recorder does not store the sentence you read in a task guide. It stores
the control and the action, and builds the sentence from an *instruction label*
that is resolved in three stages:

1. an explicit instruction label the step asks for,
2. a label named ``[control type]_[command or property]``,
3. a general-purpose fallback, ``%2 the %1`` for commands and
   ``In the %1 field, enter %2`` for properties,

where ``%1`` is the control label and ``%2`` is the command name (for commands)
or the value (for properties). Each label may also have an ``_Example`` variant,
used when the guide should tell the reader to supply their own data instead of
repeating the recorded value.

This module keeps that mechanism and swaps the label table for one that speaks
about a handheld: tap and scan rather than click and type.

Reference: "Control the text that Task Recorder generates for a control" and
"Task recorder resources" in the finance and operations documentation.
"""

from dataclasses import dataclass
from typing import Dict, Optional

COMMAND_FALLBACK = "CommandUserAction"
PROPERTY_FALLBACK = "PropertySetValue"

#: Instruction labels. Keys follow Task Recorder's `[control type]_[member]`
#: convention, with `_Example` variants for "enter your own value" wording.
INSTRUCTION_LABELS: Dict[str, str] = {
    # General-purpose fallbacks, as in the finance and operations client.
    COMMAND_FALLBACK: "%2 the %1.",
    PROPERTY_FALLBACK: "In the %1 field, enter %2.",

    # Commands.
    "Button_Tap": "Tap %1.",
    "MenuItem_Tap": "Tap %1.",
    "ListRow_Select": "In the list, select %1.",
    "Page_Close": "Close %1.",
    "Page_Back": "Tap the back arrow to leave %1.",

    # Properties.
    "Field_Value": "In the %1 field, enter %2.",
    "Field_Value_Example": "In the %1 field, enter a value.",
    "ScanField_Value": "In the %1 field, scan %2.",
    "ScanField_Value_Example": "In the %1 field, scan the value from the label.",
    "Checkbox_Value": "%2 %1.",
    "Checkbox_Value_Example": "Select or clear the %1 field.",
}


@dataclass(frozen=True)
class ActionSpec:
    """How one kind of user action maps onto the label table."""

    name: str
    control_type: str
    member: str
    is_property: bool
    verb: str = ""
    takes_value: bool = False
    default_control: str = ""

    @property
    def label_id(self) -> str:
        return f"{self.control_type}_{self.member}"

    @property
    def example_label_id(self) -> str:
        return f"{self.label_id}_Example"


#: The actions a handheld recording can hold. `tap` is the default.
ACTIONS: Dict[str, ActionSpec] = {
    "tap": ActionSpec("tap", "Button", "Tap", False, verb="Tap"),
    "menu": ActionSpec("menu", "MenuItem", "Tap", False, verb="Tap"),
    "enter": ActionSpec("enter", "Field", "Value", True, takes_value=True),
    "scan": ActionSpec("scan", "ScanField", "Value", True, takes_value=True),
    "check": ActionSpec("check", "Checkbox", "Value", True, takes_value=True),
    "select": ActionSpec("select", "ListRow", "Select", False, verb="Select"),
    "close": ActionSpec("close", "Page", "Close", False, verb="Close", default_control="the page"),
    "back": ActionSpec("back", "Page", "Back", False, verb="Leave", default_control="the page"),
}

#: Popup label -> action name, in the order the recorder offers them.
ACTION_CHOICES = [
    ("Tap a button", "tap"),
    ("Tap a menu item", "menu"),
    ("Scan a value", "scan"),
    ("Enter a value", "enter"),
    ("Select a row in a list", "select"),
    ("Select or clear a check box", "check"),
    ("Close the page", "close"),
    ("Go back", "back"),
]
ACTION_LABELS = dict(ACTION_CHOICES)

#: Wording for a value step whose control could not be read. "In the the
#: control field" is what the fallback produced, and no reader should see it.
NO_CONTROL_LABELS: Dict[str, str] = {
    "Field_Value": "Enter %2.",
    "Field_Value_Example": "Enter the value.",
    "ScanField_Value": "Scan %2.",
    "ScanField_Value_Example": "Scan the value from the label.",
    "Checkbox_Value": "%2 the check box.",
    "Checkbox_Value_Example": "Select or clear the check box.",
}

#: Values a checkbox step renders as, mirroring Task Recorder's value labels.
CHECKBOX_VALUE_LABELS = {
    "true": "Select",
    "yes": "Select",
    "on": "Select",
    "1": "Select",
    "false": "Clear",
    "no": "Clear",
    "off": "Clear",
    "0": "Clear",
}

#: How a step's value is rendered.
PREFERRED = "preferred"  # the recorded value: In the LP field, scan 'LP000123'.
EXAMPLE = "example"      # the reader's own value: In the LP field, scan the value from the label.
VALUE_MODES = (PREFERRED, EXAMPLE)


def get_action(name: Optional[str]) -> ActionSpec:
    """Look up an action, falling back to `tap` for anything unknown."""
    return ACTIONS.get((name or "tap").strip().lower(), ACTIONS["tap"])


def quote_value(value: str) -> str:
    """Render a recorded value the way a task guide shows it: 'LP000123'."""
    value = (value or "").strip()
    if not value:
        return "a value"
    if value[0] in "'\"" and value[-1] == value[0] and len(value) > 1:
        return value
    return f"'{value}'"


def resolve_label(action: ActionSpec, value_mode: str, override: Optional[str] = None) -> str:
    """Resolve the instruction label for an action, in Task Recorder's order."""
    if override:
        if override in INSTRUCTION_LABELS:
            return INSTRUCTION_LABELS[override]
        return override  # an inline template, e.g. "Scan %1 twice."

    if value_mode == EXAMPLE and action.takes_value:
        example = INSTRUCTION_LABELS.get(action.example_label_id)
        if example:
            return example

    label = INSTRUCTION_LABELS.get(action.label_id)
    if label:
        return label

    return INSTRUCTION_LABELS[PROPERTY_FALLBACK if action.is_property else COMMAND_FALLBACK]


def _value_argument(action: ActionSpec, value: str, value_mode: str) -> str:
    if action.control_type == "Checkbox":
        return CHECKBOX_VALUE_LABELS.get((value or "").strip().lower(), "Set")
    if action.is_property:
        return quote_value(value) if value_mode == PREFERRED else "a value"
    return action.verb or "Tap"


def render_instruction(
    action_name: Optional[str],
    control: str = "",
    value: str = "",
    value_mode: str = PREFERRED,
    user_text: str = "",
    instruction_label: Optional[str] = None,
) -> str:
    """Build the sentence for one step.

    `user_text` follows Task Recorder's user-supplied value label: on a step that
    carries a value it replaces the value, and on a step that does not (a button,
    say) it replaces the whole sentence.
    """
    action = get_action(action_name)
    user_text = (user_text or "").strip()

    if user_text and not action.takes_value:
        return _sentence(user_text)

    control_label = (control or "").strip() or action.default_control or "the control"
    label = resolve_label(action, value_mode, instruction_label)

    # A value step with no control name gets wording that does without one,
    # rather than "In the the control field".
    if not (control or "").strip() and action.is_property and not instruction_label:
        example = value_mode == EXAMPLE and action.takes_value
        label = NO_CONTROL_LABELS.get(
            action.example_label_id if example else action.label_id, label
        )

    if user_text:
        value_argument = user_text
        # A user-supplied value only makes sense in a label that shows the value.
        if "%2" not in label:
            label = INSTRUCTION_LABELS[PROPERTY_FALLBACK]
    else:
        value_argument = _value_argument(action, value, value_mode)

    text = label.replace("%1", control_label).replace("%2", value_argument)
    return _sentence(text)


def _sentence(text: str) -> str:
    text = " ".join(text.split())
    if text and text[0].islower():
        text = text[0].upper() + text[1:]
    if text and text[-1] not in ".!?:":
        text += "."
    return text
