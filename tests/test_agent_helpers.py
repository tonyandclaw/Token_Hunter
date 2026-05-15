from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.agent_helpers import (
    HASHABLE_FIELDS,
    accumulate_tokens,
    extract_sdk_session_id,
    hash_input,
    load_system_prompt,
)
from src.audit import sha256_short

# --- load_system_prompt ---


def test_load_system_prompt_substitutes_user_name(tmp_path: Path):
    p = tmp_path / "constitution.md"
    p.write_text("Hello {USER_NAME}, your agent here.", encoding="utf-8")
    out = load_system_prompt(path=p, user_name="Tony")
    assert out == "Hello Tony, your agent here."


def test_load_system_prompt_leaves_other_braces_alone(tmp_path: Path):
    """docs/00 has {today}, {YYYY-MM-DD} runtime placeholders we must NOT touch."""
    p = tmp_path / "constitution.md"
    p.write_text(
        "Today is {today}. User is {USER_NAME}. Format: {YYYY-MM-DD}.",
        encoding="utf-8",
    )
    out = load_system_prompt(path=p, user_name="Alice")
    assert "{today}" in out
    assert "{YYYY-MM-DD}" in out
    assert "Alice" in out
    assert "{USER_NAME}" not in out


def test_load_system_prompt_reads_user_name_from_env(tmp_path: Path, monkeypatch):
    """When `user_name=None`, fall back to USER_NAME env var (production path)."""
    p = tmp_path / "constitution.md"
    p.write_text("Hello {USER_NAME}", encoding="utf-8")
    monkeypatch.setenv("USER_NAME", "FromEnv")
    out = load_system_prompt(path=p)
    assert out == "Hello FromEnv"


def test_load_system_prompt_raises_when_no_user_name(tmp_path: Path, monkeypatch):
    p = tmp_path / "constitution.md"
    p.write_text("Hello {USER_NAME}", encoding="utf-8")
    monkeypatch.delenv("USER_NAME", raising=False)
    with pytest.raises(KeyError):
        load_system_prompt(path=p)


# --- hash_input ---


def test_hash_input_hashes_body_and_subject():
    out = hash_input({"to": "alice@acme.com", "subject": "re: order", "body": "週五交付"})
    # "to" passes through; "subject" and "body" become *_hash
    assert out["to"] == "alice@acme.com"
    assert out["subject_hash"] == sha256_short("re: order")
    assert out["body_hash"] == sha256_short("週五交付")
    assert "subject" not in out
    assert "body" not in out


def test_hash_input_handles_all_known_fields():
    out = hash_input({"subject": "s", "body": "b", "text": "t", "content": "c"})
    assert out["subject_hash"] == sha256_short("s")
    assert out["body_hash"] == sha256_short("b")
    assert out["text_hash"] == sha256_short("t")
    assert out["content_hash"] == sha256_short("c")


def test_hash_input_passes_non_string_values_through():
    """Even if the key matches HASHABLE_FIELDS, non-string values aren't hashed."""
    out = hash_input({"body": None, "count": 5, "to": "x@y"})
    assert out["body"] is None  # passes through, not hashed
    assert out["count"] == 5
    assert out["to"] == "x@y"


def test_hash_input_empty_dict():
    assert hash_input({}) == {}


def test_hash_input_is_deterministic():
    """Same content → same hash. Pinned so audit-log replay stays stable."""
    a = hash_input({"body": "hello"})
    b = hash_input({"body": "hello"})
    assert a == b


def test_hashable_fields_pinned():
    """The exact field set is part of the audit-log schema contract."""
    assert frozenset({"subject", "body", "text", "content"}) == HASHABLE_FIELDS


# --- accumulate_tokens ---


def test_accumulate_tokens_handles_object_usage():
    """Common case: SDK event has a `usage` attribute with int counts."""
    event = SimpleNamespace(usage=SimpleNamespace(input_tokens=10, output_tokens=20))
    totals = {"input": 0, "output": 0}
    accumulate_tokens(event, totals)
    assert totals == {"input": 10, "output": 20}


def test_accumulate_tokens_handles_dict_usage():
    """Some SDK paths emit events as plain dicts; we tolerate that shape too."""
    totals = {"input": 0, "output": 0}
    accumulate_tokens({"usage": {"input_tokens": 7, "output_tokens": 3}}, totals)
    assert totals == {"input": 7, "output": 3}


def test_accumulate_tokens_accumulates_across_events():
    totals = {"input": 0, "output": 0}
    for n in (5, 10, 15):
        accumulate_tokens(
            SimpleNamespace(usage=SimpleNamespace(input_tokens=n, output_tokens=n * 2)),
            totals,
        )
    assert totals == {"input": 5 + 10 + 15, "output": 10 + 20 + 30}


def test_accumulate_tokens_skips_event_with_no_usage():
    totals = {"input": 99, "output": 88}
    # No usage attribute at all — must be a no-op
    accumulate_tokens(SimpleNamespace(text="hi"), totals)
    assert totals == {"input": 99, "output": 88}


def test_accumulate_tokens_skips_event_with_partial_usage():
    """A usage object with only input_tokens should still count what it has."""
    totals = {"input": 0, "output": 0}
    accumulate_tokens(SimpleNamespace(usage=SimpleNamespace(input_tokens=4)), totals)
    assert totals == {"input": 4, "output": 0}


def test_accumulate_tokens_swallows_strange_types():
    """Never raise — if the SDK schema shifts, fall back to skipping the event."""
    totals = {"input": 0, "output": 0}
    accumulate_tokens(None, totals)
    accumulate_tokens("not an event", totals)
    accumulate_tokens(SimpleNamespace(usage="oops not a dict or object"), totals)
    assert totals == {"input": 0, "output": 0}


def test_accumulate_tokens_zero_counts_dont_increment():
    """input_tokens=0 should be a no-op, not increment by 0 falsy check."""
    totals = {"input": 5, "output": 5}
    accumulate_tokens(
        SimpleNamespace(usage=SimpleNamespace(input_tokens=0, output_tokens=0)),
        totals,
    )
    assert totals == {"input": 5, "output": 5}


# --- extract_sdk_session_id ---


def test_extract_sdk_session_id_object_shape():
    """SDK docs example shape: SystemMessage with .subtype + .data['session_id']."""
    event = SimpleNamespace(subtype="init", data={"session_id": "sess-abc123"})
    assert extract_sdk_session_id(event) == "sess-abc123"


def test_extract_sdk_session_id_dict_shape():
    """Alternate shape some SDK versions emit: plain dict."""
    event = {"subtype": "init", "session_id": "sess-xyz"}
    assert extract_sdk_session_id(event) == "sess-xyz"


def test_extract_sdk_session_id_dict_shape_with_data_nested():
    """Dict shape where session_id lives under `data` like the object form."""
    event = {"subtype": "init", "data": {"session_id": "sess-nested"}}
    assert extract_sdk_session_id(event) == "sess-nested"


def test_extract_sdk_session_id_returns_none_for_non_init():
    """Any event whose subtype isn't 'init' must return None."""
    assert (
        extract_sdk_session_id(SimpleNamespace(subtype="message", data={"session_id": "x"})) is None
    )
    assert extract_sdk_session_id({"subtype": "result", "session_id": "x"}) is None


def test_extract_sdk_session_id_returns_none_when_no_subtype():
    """No subtype attribute at all → not an init event."""
    assert extract_sdk_session_id(SimpleNamespace(text="hi")) is None
    assert extract_sdk_session_id({"other": "stuff"}) is None


def test_extract_sdk_session_id_returns_none_when_init_but_no_id():
    """Subtype is init but session_id is missing/empty — defensive None."""
    assert extract_sdk_session_id(SimpleNamespace(subtype="init", data={})) is None
    assert extract_sdk_session_id({"subtype": "init"}) is None
    assert extract_sdk_session_id({"subtype": "init", "session_id": ""}) is None


def test_extract_sdk_session_id_returns_str_even_if_id_is_int():
    """Defensive coercion: SDK could send numeric IDs in some shapes."""
    out = extract_sdk_session_id({"subtype": "init", "session_id": 12345})
    assert out == "12345"
    assert isinstance(out, str)


def test_extract_sdk_session_id_never_raises():
    """Garbage in, None out — never blow up the caller."""
    assert extract_sdk_session_id(None) is None
    assert extract_sdk_session_id("not an event") is None
    assert extract_sdk_session_id(42) is None
