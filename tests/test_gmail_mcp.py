"""Unit tests for the Gmail MCP server.

We stub GmailClient at the tool level so tests stay offline. The real
IMAP/SMTP code is only exercised by `make run` against a sandbox mailbox.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from src.tools.gmail_mcp import (
    EmailFull,
    EmailSummary,
    GmailClient,
    build_server,
    build_tools,
)


@dataclass
class FakeGmailClient:
    """Minimal stand-in for GmailClient. Records sends so tests can assert on them."""

    unread: list[EmailSummary] = field(default_factory=list)
    search_results: dict[str, list[EmailSummary]] = field(default_factory=dict)
    bodies: dict[str, EmailFull] = field(default_factory=dict)
    sent: list[tuple[str, str, str]] = field(default_factory=list)
    send_error: Exception | None = None

    def list_unread(self, limit: int) -> list[EmailSummary]:
        return self.unread[:limit]

    def search(self, query: str, limit: int) -> list[EmailSummary]:
        return self.search_results.get(query, [])[:limit]

    def read(self, uid: str) -> EmailFull | None:
        return self.bodies.get(uid)

    def send(self, to: str, subject: str, body: str) -> str:
        if self.send_error:
            raise self.send_error
        self.sent.append((to, subject, body))
        return "sent"


def _factory(client) -> object:
    def f():
        return client

    return f


def _tool_by_name(tools, name: str):
    return next(t for t in tools if t.name == name)


async def test_list_unread_renders_summaries():
    fake = FakeGmailClient(
        unread=[
            EmailSummary("100", "alice@a.com", "re: 報價", "2026-05-13", "請看附件"),
            EmailSummary("101", "bob@b.com", "週會", "2026-05-13", "今天 15:00 開會"),
        ]
    )
    tools = build_tools(_factory(fake))
    result = await _tool_by_name(tools, "list_unread").handler({"limit": 20})
    text = result["content"][0]["text"]
    assert "uid=100" in text
    assert "alice@a.com" in text
    assert "請看附件" in text
    assert "uid=101" in text


async def test_list_unread_empty_returns_friendly_message():
    fake = FakeGmailClient(unread=[])
    tools = build_tools(_factory(fake))
    result = await _tool_by_name(tools, "list_unread").handler({"limit": 20})
    assert "沒有符合條件" in result["content"][0]["text"]


async def test_list_unread_respects_limit():
    items = [EmailSummary(str(i), "x", "y", "z", "snippet") for i in range(10)]
    fake = FakeGmailClient(unread=items)
    tools = build_tools(_factory(fake))
    result = await _tool_by_name(tools, "list_unread").handler({"limit": 3})
    text = result["content"][0]["text"]
    assert text.count("uid=") == 3


async def test_search_uses_gmail_query():
    hits = [EmailSummary("200", "carol@c.com", "PR review", "2026-05-13", "...")]
    fake = FakeGmailClient(search_results={"from:carol": hits})
    tools = build_tools(_factory(fake))
    result = await _tool_by_name(tools, "search").handler({"query": "from:carol", "limit": 20})
    assert "uid=200" in result["content"][0]["text"]


async def test_read_full_message_includes_headers_and_body():
    fake = FakeGmailClient(
        bodies={
            "100": EmailFull(
                uid="100",
                sender="alice@a.com",
                to=("me@x.com",),
                subject="hi",
                date="2026-05-13",
                body="hello, world",
                attachments=("a.pdf",),
            )
        }
    )
    tools = build_tools(_factory(fake))
    result = await _tool_by_name(tools, "read").handler({"uid": "100"})
    text = result["content"][0]["text"]
    assert "alice@a.com" in text
    assert "me@x.com" in text
    assert "hello, world" in text
    assert "a.pdf" in text


async def test_read_missing_uid_is_error():
    fake = FakeGmailClient()
    tools = build_tools(_factory(fake))
    result = await _tool_by_name(tools, "read").handler({"uid": "999"})
    assert result["is_error"] is True
    assert "999" in result["content"][0]["text"]


async def test_send_records_args_and_reports_sent():
    fake = FakeGmailClient()
    tools = build_tools(_factory(fake))
    result = await _tool_by_name(tools, "send").handler(
        {"to": "alice@a.com", "subject": "re: 報價", "body": "週五交付。"},
    )
    assert "sent" in result["content"][0]["text"]
    assert fake.sent == [("alice@a.com", "re: 報價", "週五交付。")]


async def test_client_factory_failure_surfaces_as_tool_error():
    def boom():
        raise RuntimeError("GMAIL_ADDRESS / GMAIL_APP_PASSWORD not set")

    tools = build_tools(boom)
    result = await _tool_by_name(tools, "list_unread").handler({"limit": 10})
    assert result["is_error"] is True
    assert "Gmail unavailable" in result["content"][0]["text"]


def test_build_server_names_server_gmail():
    fake = FakeGmailClient()
    server = build_server(_factory(fake))
    assert server["name"] == "gmail"
    assert server["type"] == "sdk"


def test_client_from_env_missing_env_raises(monkeypatch):
    monkeypatch.delenv("GMAIL_ADDRESS", raising=False)
    monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)
    with pytest.raises(RuntimeError, match="GMAIL_ADDRESS"):
        GmailClient.from_env()


def test_client_from_env_uses_overrides(monkeypatch):
    monkeypatch.setenv("GMAIL_ADDRESS", "x@y")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "secret")
    monkeypatch.setenv("GMAIL_IMAP_HOST", "imap.example.com")
    monkeypatch.setenv("GMAIL_SMTP_HOST", "smtp.example.com")
    c = GmailClient.from_env()
    assert c.address == "x@y"
    assert c.imap_host == "imap.example.com"
    assert c.smtp_host == "smtp.example.com"
