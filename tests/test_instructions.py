import pytest

from whs_recorder.instructions import (
    COMMAND_FALLBACK,
    EXAMPLE,
    INSTRUCTION_LABELS,
    PREFERRED,
    PROPERTY_FALLBACK,
    get_action,
    quote_value,
    render_instruction,
    resolve_label,
)


def test_general_purpose_fallbacks_match_the_client():
    """Task Recorder's documented fallbacks: '%2 the %1' and 'In the %1 field, enter %2'."""
    assert INSTRUCTION_LABELS[COMMAND_FALLBACK] == "%2 the %1."
    assert INSTRUCTION_LABELS[PROPERTY_FALLBACK] == "In the %1 field, enter %2."


def test_button_step_reads_as_a_tap():
    assert render_instruction("tap", "Inbound") == "Tap Inbound."


def test_field_step_repeats_the_recorded_value():
    assert render_instruction("enter", "Quantity", "12") == "In the Quantity field, enter '12'."


def test_scan_step_uses_the_scan_wording():
    assert render_instruction("scan", "LP", "LP000123") == "In the LP field, scan 'LP000123'."


def test_example_mode_asks_the_reader_for_their_own_value():
    assert render_instruction("enter", "Quantity", "12", value_mode=EXAMPLE) == (
        "In the Quantity field, enter a value."
    )
    assert render_instruction("scan", "LP", "LP000123", value_mode=EXAMPLE) == (
        "In the LP field, scan the value from the label."
    )


def test_example_mode_leaves_command_steps_alone():
    """Steps that aren't related to fields have no example value label."""
    assert render_instruction("tap", "Post", value_mode=EXAMPLE) == "Tap Post."


def test_checkbox_uses_a_value_label_rather_than_true_or_false():
    assert render_instruction("check", "Full pallet", "true") == "Select Full pallet."
    assert render_instruction("check", "Full pallet", "false") == "Clear Full pallet."
    assert render_instruction("check", "Full pallet", "", value_mode=EXAMPLE) == (
        "Select or clear the Full pallet field."
    )


def test_user_text_replaces_the_whole_sentence_on_a_command_step():
    assert render_instruction("tap", "Post", user_text="To post the receipt, tap Post") == (
        "To post the receipt, tap Post."
    )


def test_user_text_replaces_only_the_value_on_a_field_step():
    assert render_instruction("enter", "Quantity", "12", user_text="the quantity on the packing slip") == (
        "In the Quantity field, enter the quantity on the packing slip."
    )


def test_user_text_on_a_field_step_survives_a_label_without_a_value_slot():
    text = render_instruction("enter", "Quantity", "12", user_text="a number", instruction_label="Tap %1.")
    assert text == "In the Quantity field, enter a number."


def test_an_explicit_label_id_wins():
    assert resolve_label(get_action("tap"), PREFERRED, override="MenuItem_Tap") == "Tap %1."


def test_an_explicit_template_is_used_verbatim():
    assert render_instruction("tap", "Confirm", instruction_label="Press %1 twice.") == "Press Confirm twice."


def test_unknown_action_falls_back_to_tap():
    assert get_action("does-not-exist").name == "tap"
    assert render_instruction("does-not-exist", "Something") == "Tap Something."


def test_page_actions_have_a_default_control():
    assert render_instruction("close") == "Close the page."
    assert render_instruction("back") == "Tap the back arrow to leave the page."


def test_missing_control_never_produces_a_dangling_sentence():
    assert render_instruction("tap", "") == "Tap the control."


@pytest.mark.parametrize(
    "value,expected",
    [("LP1", "'LP1'"), ("'LP1'", "'LP1'"), ('"LP1"', '"LP1"'), ("", "a value"), ("  ", "a value")],
)
def test_value_quoting(value, expected):
    assert quote_value(value) == expected


def test_sentences_are_capitalised_and_terminated():
    assert render_instruction("tap", "post") == "Tap post."
    assert render_instruction("tap", "Post", user_text="check the label first") == "Check the label first."
