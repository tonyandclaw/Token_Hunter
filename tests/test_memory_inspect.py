from __future__ import annotations

from pathlib import Path

from src.memory_inspect import (
    MAX_PROFILE_CHARS,
    render_learnings,
    render_user_profile,
)


def test_render_user_profile_missing_file(tmp_path: Path):
    out = render_user_profile(tmp_path / "no-such.md")
    assert "尚未建立" in out
    assert "user-profile.md" in out


def test_render_user_profile_empty_file(tmp_path: Path):
    p = tmp_path / "user-profile.md"
    p.write_text("", encoding="utf-8")
    out = render_user_profile(p)
    assert "空的" in out


def test_render_user_profile_shows_content(tmp_path: Path):
    p = tmp_path / "user-profile.md"
    p.write_text(
        "- (2026-05-13) 偏好回信簡短\n- (2026-05-14) 對 ACME 用「週五」交期\n",
        encoding="utf-8",
    )
    out = render_user_profile(p)
    assert "偏好回信簡短" in out
    assert "ACME" in out


def test_render_user_profile_truncates_long_content(tmp_path: Path):
    p = tmp_path / "user-profile.md"
    long = ("- (2026-05-14) " + "x" * 100 + "\n") * 200
    p.write_text(long, encoding="utf-8")
    out = render_user_profile(p)
    assert "truncated" in out
    # truncation keeps the tail (most recent additions)
    assert len(out) < MAX_PROFILE_CHARS + 300  # +300 for header & ellipsis marker


def test_render_learnings_missing_file(tmp_path: Path):
    out = render_learnings(tmp_path / "no-such.md")
    assert "尚未建立" in out


def test_render_learnings_empty_blocks(tmp_path: Path):
    p = tmp_path / "learnings.md"
    p.write_text("just freeform text, no `## [Cat]` blocks\n", encoding="utf-8")
    out = render_learnings(p)
    assert "沒有結構化的規則 block" in out


def test_render_learnings_shows_most_recent_n(tmp_path: Path):
    """With more entries than the limit, only the most recent show up."""
    p = tmp_path / "learnings.md"
    blocks = []
    for i in range(8):
        blocks.append(
            f"## [cat{i}] - 2026-05-{10 + i:02d}\n\n"
            f"**觀察**:obs {i}\n\n"
            f"**推論規則**:rule {i}\n\n"
            f"**信心度**:中(觀察 3 次)\n\n"
            f"**反例**:(無)\n"
        )
    p.write_text("\n".join(blocks), encoding="utf-8")
    out = render_learnings(p, limit=3)
    assert "8 條規則" in out
    assert "顯示最新 3" in out
    assert "省略 5" in out
    # last 3 are cat5, cat6, cat7
    assert "cat7" in out
    assert "cat6" in out
    assert "cat5" in out
    # first ones are NOT shown
    assert "cat0" not in out
    assert "cat1" not in out


def test_render_learnings_shows_observation_and_rule(tmp_path: Path):
    p = tmp_path / "learnings.md"
    p.write_text(
        "## [ACME 交期] - 2026-05-14\n\n"
        "**觀察**:幾次回覆都用「週五交付」\n\n"
        "**推論規則**:ACME 詢問交期 → 回「週五」\n\n"
        "**信心度**:高(觀察 7 次)\n\n"
        "**反例**:(無)\n",
        encoding="utf-8",
    )
    out = render_learnings(p)
    assert "ACME 交期" in out
    assert "幾次回覆都用「週五交付」" in out
    assert "ACME 詢問交期 → 回「週五」" in out
    assert "信心=高" in out


def test_render_learnings_truncates_long_fields(tmp_path: Path):
    """Each observation/rule string is truncated at 120 chars."""
    p = tmp_path / "learnings.md"
    p.write_text(
        "## [cat] - 2026-05-14\n\n"
        "**觀察**:" + "x" * 500 + "\n\n"
        "**推論規則**:" + "y" * 500 + "\n\n"
        "**信心度**:中(觀察 3 次)\n\n"
        "**反例**:(無)\n",
        encoding="utf-8",
    )
    out = render_learnings(p)
    # Tail of the long observation/rule should be cut off
    # (we keep first 120 chars, so the 500th char isn't there)
    assert "x" * 200 not in out
    assert "y" * 200 not in out
