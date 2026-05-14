"""Tests for the memory MCP tool wrappers (write_user_profile, write_learning)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.tools.memory_mcp import build_server, build_tools


def _tool(name: str):
    return next(t for t in build_tools() if t.name == name)


@pytest.fixture
def memdir(tmp_path: Path, monkeypatch):
    """Redirect memory_writes to a tmp dir so the tool calls write there."""
    import src.memory_writes as mw

    monkeypatch.setattr(mw, "USER_PROFILE_PATH", tmp_path / "user-profile.md")
    monkeypatch.setattr(mw, "LEARNINGS_PATH", tmp_path / "learnings.md")
    return tmp_path


async def test_write_user_profile_writes_to_disk(memdir: Path):
    result = await _tool("write_user_profile").handler({"note": "我用繁體中文"})
    assert "L2 已寫入" in result["content"][0]["text"]
    assert "我用繁體中文" in (memdir / "user-profile.md").read_text(encoding="utf-8")


async def test_write_user_profile_rejects_empty_note():
    result = await _tool("write_user_profile").handler({"note": "   "})
    assert result["is_error"] is True
    assert "note is required" in result["content"][0]["text"]


async def test_write_learning_happy_path(memdir: Path):
    result = await _tool("write_learning").handler(
        {
            "category": "ACME",
            "observation": "回信都用「週五交付」",
            "rule": "ACME 詢問交期 → 回「週五交付」",
            "confidence": "低",
            "counter_example": "",
        }
    )
    text = result["content"][0]["text"]
    assert "L3 已寫入" in text
    assert "**信心度**:低" in text
    file_text = (memdir / "learnings.md").read_text(encoding="utf-8")
    assert "## [ACME]" in file_text


async def test_write_learning_high_request_surfaces_downgrade_warning(memdir: Path):
    result = await _tool("write_learning").handler(
        {
            "category": "新類別",
            "observation": "o",
            "rule": "r",
            "confidence": "高",
            "counter_example": "",
        }
    )
    text = result["content"][0]["text"]
    assert text.startswith("⚠️ ")
    assert "降級為「低」" in text
    assert "**信心度**:低" in text


async def test_write_learning_missing_required_fields_returns_error():
    result = await _tool("write_learning").handler(
        {
            "category": "",
            "observation": "o",
            "rule": "",
            "confidence": "低",
            "counter_example": "",
        }
    )
    assert result["is_error"] is True
    assert "category" in result["content"][0]["text"]
    assert "rule" in result["content"][0]["text"]


async def test_write_learning_rejects_unknown_confidence():
    result = await _tool("write_learning").handler(
        {
            "category": "c",
            "observation": "o",
            "rule": "r",
            "confidence": "super-high",
            "counter_example": "",
        }
    )
    assert result["is_error"] is True
    assert "confidence" in result["content"][0]["text"]


def test_build_server_names_server_memory():
    server = build_server()
    assert server["name"] == "memory"
    assert server["type"] == "sdk"
