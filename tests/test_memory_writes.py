from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.memory_writes import (
    HIGH_CONFIDENCE_MIN_OBS,
    append_learning,
    append_user_profile,
    count_observations,
    list_categories,
)


def test_append_user_profile_appends_dated_bullet(tmp_path: Path):
    p = tmp_path / "user-profile.md"
    now = datetime(2026, 5, 14, tzinfo=UTC)
    append_user_profile("我是 Tony", path=p, now=now)
    append_user_profile("我喜歡早上 9 點開始工作", path=p, now=now)
    text = p.read_text(encoding="utf-8")
    assert "(2026-05-14) 我是 Tony" in text
    assert "(2026-05-14) 我喜歡早上 9 點開始工作" in text
    assert text.count("\n- ") == 2


def test_append_learning_writes_four_field_block(tmp_path: Path):
    p = tmp_path / "learnings.md"
    now = datetime(2026, 5, 14, tzinfo=UTC)
    block, warning = append_learning(
        category="ACME 客戶",
        observation="使用者連續 5 次回覆「週五交付」",
        rule="遇到 ACME 詢問交期 → 起草「週五交付」",
        confidence="低",
        path=p,
        now=now,
    )
    assert warning is None
    assert "## [ACME 客戶] - 2026-05-14" in block
    assert "**觀察**:使用者連續 5 次回覆「週五交付」" in block
    assert "**推論規則**:遇到 ACME 詢問交期 → 起草「週五交付」" in block
    assert "**信心度**:低(觀察 1 次)" in block
    assert "**反例**:(無)" in block


def test_append_learning_records_counter_example_when_provided(tmp_path: Path):
    p = tmp_path / "learnings.md"
    block, _ = append_learning(
        category="cat",
        observation="o",
        rule="r",
        confidence="低",
        counter_example="2026-04-26 急件改週四下午",
        path=p,
    )
    assert "**反例**:2026-04-26 急件改週四下午" in block


def test_append_learning_increments_observation_count(tmp_path: Path):
    p = tmp_path / "learnings.md"
    for i in range(3):
        block, _ = append_learning(
            category="cat",
            observation=f"obs {i}",
            rule="r",
            confidence="低",
            path=p,
        )
        assert f"觀察 {i + 1} 次" in block
    assert count_observations("cat", path=p) == 3


def test_append_learning_high_downgrades_below_threshold(tmp_path: Path):
    p = tmp_path / "learnings.md"
    block, warning = append_learning(
        category="never_seen_before",
        observation="o",
        rule="r",
        confidence="高",
        path=p,
    )
    assert warning is not None
    assert "降級為「低」" in warning
    assert "**信心度**:低(觀察 1 次)" in block
    assert "**信心度**:高" not in block


def test_append_learning_high_allowed_after_threshold(tmp_path: Path):
    p = tmp_path / "learnings.md"
    # Seed HIGH_CONFIDENCE_MIN_OBS - 1 prior low entries; the next "高" makes it cross
    for i in range(HIGH_CONFIDENCE_MIN_OBS - 1):
        append_learning("cat", f"obs {i}", "r", "低", path=p)

    block, warning = append_learning("cat", "final", "r", "高", path=p)
    assert warning is None
    assert f"**信心度**:高(觀察 {HIGH_CONFIDENCE_MIN_OBS} 次)" in block


def test_append_learning_categories_independent(tmp_path: Path):
    p = tmp_path / "learnings.md"
    for _ in range(HIGH_CONFIDENCE_MIN_OBS):
        append_learning("ACME", "o", "r", "低", path=p)
    # Different category should still need its own observations
    block, warning = append_learning("BetaCorp", "first", "r", "高", path=p)
    assert warning is not None
    assert "**信心度**:低(觀察 1 次)" in block


def test_append_learning_rejects_unknown_confidence(tmp_path: Path):
    with pytest.raises(ValueError, match="confidence"):
        append_learning("cat", "o", "r", "very-high", path=tmp_path / "x.md")  # type: ignore[arg-type]


def test_list_categories_orders_by_count_then_name(tmp_path: Path):
    p = tmp_path / "learnings.md"
    for _ in range(2):
        append_learning("ACME", "o", "r", "低", path=p)
    append_learning("BetaCorp", "o", "r", "低", path=p)
    append_learning("ACME", "o", "r", "低", path=p)  # ACME total = 3
    assert list_categories(path=p) == [("ACME", 3), ("BetaCorp", 1)]


def test_append_user_profile_creates_parent_dir(tmp_path: Path):
    deep = tmp_path / "a" / "b" / "c" / "user-profile.md"
    append_user_profile("hello", path=deep)
    assert deep.exists()


def test_writes_never_overwrite_existing_content(tmp_path: Path):
    p = tmp_path / "user-profile.md"
    p.write_text("# existing header\n\nold content here\n", encoding="utf-8")
    append_user_profile("new fact", path=p)
    text = p.read_text(encoding="utf-8")
    assert "old content here" in text
    assert "new fact" in text
