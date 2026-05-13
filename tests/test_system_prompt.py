"""Smoke test: agent loads docs/00-agent-identity.md and substitutes USER_NAME."""

from __future__ import annotations

import os

from src.agent import load_system_prompt


def test_load_system_prompt_substitutes_user_name(monkeypatch):
    monkeypatch.setenv("USER_NAME", "Tester")
    prompt = load_system_prompt()
    assert "Tester" in prompt
    assert "Tier 3" in prompt
    assert "Tier 1" in prompt
    assert "{USER_NAME}" not in prompt  # fully substituted


def test_constitution_is_docs_00(monkeypatch):
    """Confirm we never accidentally load CLAUDE.md as system_prompt."""
    monkeypatch.setenv("USER_NAME", "x")
    prompt = load_system_prompt()
    # CLAUDE.md-only sentinel string from the dev guidance file
    assert "Claude Code (claude.ai/code)" not in prompt
