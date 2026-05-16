from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from src import session_log


def test_ensure_today_creates_header(tmp_path: Path):
    now = datetime(2026, 5, 13, 9, 0, tzinfo=UTC)
    path = session_log.ensure_today(tmp_path, now=now)
    assert path.exists()
    assert path.name == "2026-05-13.md"
    assert path.read_text(encoding="utf-8").startswith("# Session log — 2026-05-13")


def test_ensure_today_is_idempotent(tmp_path: Path):
    now = datetime(2026, 5, 13, tzinfo=UTC)
    p1 = session_log.ensure_today(tmp_path, now=now)
    p1.write_text("custom content\n", encoding="utf-8")
    p2 = session_log.ensure_today(tmp_path, now=now)
    assert p1 == p2
    # Existing content not overwritten
    assert p2.read_text(encoding="utf-8") == "custom content\n"


def test_append_entry_format(tmp_path: Path):
    now = datetime(2026, 5, 13, 8, 23, 11, tzinfo=UTC)
    session_log.append_entry("looked at Gmail", sessions_dir=tmp_path, now=now)
    line = (tmp_path / "2026-05-13.md").read_text(encoding="utf-8").splitlines()[-1]
    assert line == "- `08:23:11Z` looked at Gmail"


def test_read_user_corpus_extracts_user_lines_only(tmp_path: Path):
    now = datetime(2026, 5, 14, 12, 0, tzinfo=UTC)
    session_log.append_entry("user[42]: 週五交付沒問題", sessions_dir=tmp_path, now=now)
    session_log.append_entry("agent[42]: 收到", sessions_dir=tmp_path, now=now)
    session_log.append_entry("user[42]: 明天再確認規格", sessions_dir=tmp_path, now=now)
    corpus = session_log.read_user_corpus(tmp_path, now=now)
    assert "週五交付沒問題" in corpus
    assert "明天再確認規格" in corpus
    # Agent line is filtered out
    assert "收到" not in corpus


def test_read_user_corpus_respects_days_window(tmp_path: Path):
    today = datetime(2026, 5, 14, 12, 0, tzinfo=UTC)
    long_ago = today - timedelta(days=30)
    session_log.append_entry("user[1]: stale message", sessions_dir=tmp_path, now=long_ago)
    session_log.append_entry("user[1]: fresh message", sessions_dir=tmp_path, now=today)
    corpus = session_log.read_user_corpus(tmp_path, days=7, now=today)
    assert "fresh message" in corpus
    assert "stale message" not in corpus


def test_read_user_corpus_missing_dir_returns_empty(tmp_path: Path):
    assert session_log.read_user_corpus(tmp_path / "does-not-exist") == ""


def test_prune_old_drops_files_older_than_retention(tmp_path: Path):
    today = datetime(2026, 5, 13, tzinfo=UTC)
    # 35 days ago — should be pruned
    old = today - timedelta(days=35)
    (tmp_path / f"{old.strftime('%Y-%m-%d')}.md").write_text("old", encoding="utf-8")
    # 10 days ago — keep
    recent = today - timedelta(days=10)
    (tmp_path / f"{recent.strftime('%Y-%m-%d')}.md").write_text("recent", encoding="utf-8")
    # Non-date file — leave alone
    (tmp_path / "README.md").write_text("notes", encoding="utf-8")

    removed = session_log.prune_old(tmp_path, now=today)
    removed_names = {p.name for p in removed}
    assert f"{old.strftime('%Y-%m-%d')}.md" in removed_names
    assert f"{recent.strftime('%Y-%m-%d')}.md" not in removed_names
    assert (tmp_path / "README.md").exists()
