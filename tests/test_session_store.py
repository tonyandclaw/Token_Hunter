from __future__ import annotations

import json
from pathlib import Path

from src.session_store import SessionStore


def test_load_returns_empty_when_missing(tmp_path: Path):
    s = SessionStore(path=tmp_path / "no-such.json")
    s.load()
    assert s.get("any-user") is None
    assert s.all() == {}


def test_set_persists_immediately(tmp_path: Path):
    path = tmp_path / "sessions.json"
    s = SessionStore(path=path)
    s.set("user-1", "sess-abc")
    assert path.exists()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload == {"user-1": "sess-abc"}


def test_get_returns_what_set_persisted(tmp_path: Path):
    path = tmp_path / "sessions.json"
    s = SessionStore(path=path)
    s.set("user-1", "sess-abc")
    # Fresh instance reads what the prior wrote
    s2 = SessionStore(path=path)
    s2.load()
    assert s2.get("user-1") == "sess-abc"


def test_set_skips_write_when_unchanged(tmp_path: Path):
    """Don't churn the file when set() is called with the same value."""
    path = tmp_path / "sessions.json"
    s = SessionStore(path=path)
    s.set("user-1", "sess-abc")
    mtime1 = path.stat().st_mtime_ns
    # Set the same value — should be a no-op
    s.set("user-1", "sess-abc")
    mtime2 = path.stat().st_mtime_ns
    assert mtime1 == mtime2


def test_set_with_empty_value_is_noop(tmp_path: Path):
    """Defensive: passing an empty session_id shouldn't write."""
    path = tmp_path / "sessions.json"
    s = SessionStore(path=path)
    s.set("user-1", "")
    assert not path.exists()


def test_forget_removes_entry(tmp_path: Path):
    path = tmp_path / "sessions.json"
    s = SessionStore(path=path)
    s.set("user-1", "sess-abc")
    s.set("user-2", "sess-xyz")
    s.forget("user-1")
    s2 = SessionStore(path=path)
    s2.load()
    assert s2.get("user-1") is None
    assert s2.get("user-2") == "sess-xyz"


def test_forget_unknown_user_is_noop(tmp_path: Path):
    """forget() on a user we don't have shouldn't crash or touch the file."""
    path = tmp_path / "sessions.json"
    s = SessionStore(path=path)
    s.set("user-1", "sess-abc")
    s.forget("never-existed")
    # File still has user-1
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload == {"user-1": "sess-abc"}


def test_load_recovers_from_corrupt_file(tmp_path: Path):
    """A truncated/garbled file from a crash mid-write must not crash the bot.

    Losing one turn of context is acceptable; crashing the whole bot is not.
    """
    path = tmp_path / "sessions.json"
    path.write_text("{not valid json", encoding="utf-8")
    s = SessionStore(path=path)
    s.load()
    assert s.all() == {}


def test_load_coerces_legacy_payload_to_strings(tmp_path: Path):
    """If a previous version wrote int keys/values, coerce to str on load."""
    path = tmp_path / "sessions.json"
    path.write_text(json.dumps({"123": 456, "abc": "def"}), encoding="utf-8")
    s = SessionStore(path=path)
    s.load()
    assert s.get("123") == "456"
    assert s.get("abc") == "def"


def test_atomic_write_does_not_leave_tmp_files(tmp_path: Path):
    """No `.tmp` litter in the directory after a successful save."""
    path = tmp_path / "sessions.json"
    s = SessionStore(path=path)
    s.set("user-1", "sess-abc")
    tmp_files = list(tmp_path.glob(".*.tmp"))
    assert tmp_files == []


def test_all_returns_snapshot_not_live_dict(tmp_path: Path):
    """all() returns a copy — mutating it must NOT corrupt internal state."""
    s = SessionStore(path=tmp_path / "x.json")
    s.set("user-1", "sess-abc")
    snap = s.all()
    snap["user-1"] = "tampered"
    assert s.get("user-1") == "sess-abc"


def test_count_reflects_persisted_users(tmp_path: Path):
    """count() is the cheap O(1) shape that /status uses for logging."""
    s = SessionStore(path=tmp_path / "x.json")
    assert s.count() == 0
    s.set("u1", "a")
    s.set("u2", "b")
    assert s.count() == 2
    s.forget("u1")
    assert s.count() == 1
