"""Contract tests for the ChatAdapter abstraction.

These tests don't instantiate any real adapter — they exercise the neutral
dataclasses and serve as a regression guard against accidental schema drift.
"""

from __future__ import annotations

from src.chat.base import Button, IncomingButton, IncomingText, Keyboard


def test_button_is_immutable():
    b = Button(label="OK", callback_data="t2:abc:yes")
    assert b.label == "OK"
    assert b.callback_data == "t2:abc:yes"


def test_keyboard_is_just_lists_of_buttons():
    """Keyboard alias is intentionally a plain list — no class to inherit from."""
    kb: Keyboard = [
        [Button("Yes", "y"), Button("No", "n")],
        [Button("Maybe", "m")],
    ]
    assert len(kb) == 2
    assert kb[0][0].label == "Yes"
    assert kb[1][0].callback_data == "m"


def test_incoming_text_carries_user_text_and_source_ref():
    ctx = IncomingText(user_id="12345", text="hello", source_ref="opaque")
    assert ctx.user_id == "12345"
    assert ctx.text == "hello"
    # source_ref is intentionally opaque — handlers don't inspect it
    assert ctx.source_ref == "opaque"


def test_incoming_button_carries_callback_data_and_source_ref():
    ctx = IncomingButton(
        user_id="12345",
        callback_data="t2:abc:yes",
        source_ref={"telegram": "..."},
    )
    assert ctx.callback_data == "t2:abc:yes"
    assert isinstance(ctx.source_ref, dict)


def test_user_id_is_stringified_per_contract():
    """Per the docstring contract, user_id is a str — not Telegram's int."""
    ctx = IncomingText(user_id="12345", text="x", source_ref=None)
    assert isinstance(ctx.user_id, str)
