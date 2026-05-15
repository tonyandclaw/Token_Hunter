from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from src.voice_corpus import (
    DEFAULT_RECENT_DAYS,
    MAX_CORPUS_CHARS,
    load_user_corpus,
)


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_load_returns_empty_when_no_sources(tmp_path):
    out = load_user_corpus(
        profile_path=tmp_path / "user-profile.md",
        sessions_dir=tmp_path / "sessions",
    )
    assert out == ""


def test_load_reads_l2_user_profile(tmp_path):
    _write(
        tmp_path / "user-profile.md",
        "- (2026-05-14) 我寫信偏簡短,常以「了解」結尾。\n",
    )
    out = load_user_corpus(
        profile_path=tmp_path / "user-profile.md",
        sessions_dir=tmp_path / "sessions",
    )
    assert "簡短" in out
    assert "「了解」" in out


def test_load_extracts_user_lines_from_l4(tmp_path):
    """Only `user[NNN]: ...` lines from session logs end up in the corpus."""
    _write(
        tmp_path / "sessions" / "2026-05-14.md",
        "# Session log — 2026-05-14\n\n"
        "- `09:00:00Z` user[111]: 幫我看一下 ACME 那封信\n"
        "- `09:00:01Z` agent[111]: 好的,以下是摘要 ...\n"
        "- `10:00:00Z` user[111]: 回覆「週五交付」就好\n",
    )
    out = load_user_corpus(
        profile_path=tmp_path / "user-profile.md",
        sessions_dir=tmp_path / "sessions",
        now=datetime(2026, 5, 14, tzinfo=UTC),
    )
    assert "幫我看一下 ACME 那封信" in out
    assert "回覆「週五交付」就好" in out
    # agent lines must NOT leak in
    assert "好的,以下是摘要" not in out


def test_load_ignores_session_files_outside_window(tmp_path):
    _write(
        tmp_path / "sessions" / "2026-04-01.md",
        "- `09:00:00Z` user[111]: 很久以前的訊息\n",
    )
    _write(
        tmp_path / "sessions" / "2026-05-14.md",
        "- `09:00:00Z` user[111]: 今天的訊息\n",
    )
    out = load_user_corpus(
        profile_path=tmp_path / "user-profile.md",
        sessions_dir=tmp_path / "sessions",
        days=7,
        now=datetime(2026, 5, 14, tzinfo=UTC),
    )
    assert "今天的訊息" in out
    assert "很久以前的訊息" not in out


def test_load_merges_l2_and_l4(tmp_path):
    _write(tmp_path / "user-profile.md", "L2 fact about user.")
    _write(
        tmp_path / "sessions" / "2026-05-14.md",
        "- `09:00:00Z` user[111]: L4 user line.\n",
    )
    out = load_user_corpus(
        profile_path=tmp_path / "user-profile.md",
        sessions_dir=tmp_path / "sessions",
        now=datetime(2026, 5, 14, tzinfo=UTC),
    )
    assert "L2 fact about user." in out
    assert "L4 user line." in out


def test_load_caps_total_corpus_size(tmp_path):
    """When the combined corpus exceeds max_chars, oldest content is trimmed."""
    _write(tmp_path / "user-profile.md", "A" * 5000)
    _write(
        tmp_path / "sessions" / "2026-05-14.md",
        "- `09:00:00Z` user[111]: " + ("B" * 5000) + "\n",
    )
    out = load_user_corpus(
        profile_path=tmp_path / "user-profile.md",
        sessions_dir=tmp_path / "sessions",
        max_chars=4000,
        now=datetime(2026, 5, 14, tzinfo=UTC),
    )
    assert len(out) == 4000
    # The tail (newest L4 content) survives; the L2 head is dropped first
    assert "B" in out


def test_load_skips_malformed_session_filenames(tmp_path):
    """Files in sessions/ whose stem isn't an ISO date are ignored."""
    _write(
        tmp_path / "sessions" / "not-a-date.md",
        "- `09:00:00Z` user[111]: should be ignored\n",
    )
    _write(
        tmp_path / "sessions" / "2026-05-14.md",
        "- `09:00:00Z` user[111]: should be kept\n",
    )
    out = load_user_corpus(
        profile_path=tmp_path / "user-profile.md",
        sessions_dir=tmp_path / "sessions",
        now=datetime(2026, 5, 14, tzinfo=UTC),
    )
    assert "should be kept" in out
    assert "should be ignored" not in out


def test_defaults_are_sane():
    """Pin the public constants so they don't drift accidentally."""
    assert DEFAULT_RECENT_DAYS == 7
    assert MAX_CORPUS_CHARS == 20_000
