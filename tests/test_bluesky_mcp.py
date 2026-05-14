from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from src.tools.bluesky_mcp import BlueskyClient, Post, build_server, build_tools


@dataclass
class FakeBlueskyClient:
    feed: list[Post] = field(default_factory=list)
    search_results: dict[str, list[Post]] = field(default_factory=dict)
    posted: list[str] = field(default_factory=list)
    replies: list[tuple[str, str, str]] = field(default_factory=list)
    post_uri_seq: int = 0

    def _next_post(self, text: str, author: str = "me") -> Post:
        self.post_uri_seq += 1
        return Post(
            uri=f"at://did:plc:test/app.bsky.feed.post/{self.post_uri_seq}",
            cid=f"cid-{self.post_uri_seq}",
            author=author,
            text=text,
            created_at="2026-05-14T00:00:00Z",
        )

    def timeline(self, limit: int) -> list[Post]:
        return self.feed[:limit]

    def search(self, query: str, limit: int) -> list[Post]:
        return self.search_results.get(query, [])[:limit]

    def post(self, text: str) -> Post:
        p = self._next_post(text)
        self.posted.append(text)
        return p

    def reply(self, parent_uri: str, parent_cid: str, text: str) -> Post:
        p = self._next_post(text)
        self.replies.append((parent_uri, parent_cid, text))
        return p


def _factory(client) -> object:
    def f():
        return client

    return f


def _tool(tools, name: str):
    return next(t for t in tools if t.name == name)


async def test_timeline_renders_posts():
    fake = FakeBlueskyClient(
        feed=[
            Post("at://1", "cid-1", "alice", "hello world", "2026-05-13"),
            Post("at://2", "cid-2", "bob", "🌧️ 雨下整天了", "2026-05-13"),
        ]
    )
    tools = build_tools(_factory(fake))
    text = (await _tool(tools, "timeline").handler({"limit": 50}))["content"][0]["text"]
    assert "@alice" in text
    assert "hello world" in text
    assert "@bob" in text
    assert "🌧️ 雨下整天了" in text
    assert "at://1" in text
    assert "cid-1" in text


async def test_timeline_empty_returns_friendly_message():
    fake = FakeBlueskyClient()
    tools = build_tools(_factory(fake))
    text = (await _tool(tools, "timeline").handler({"limit": 50}))["content"][0]["text"]
    assert "沒有符合條件" in text


async def test_timeline_respects_limit():
    feed = [Post(f"at://{i}", f"c{i}", "x", "y", "z") for i in range(10)]
    fake = FakeBlueskyClient(feed=feed)
    tools = build_tools(_factory(fake))
    text = (await _tool(tools, "timeline").handler({"limit": 3}))["content"][0]["text"]
    assert text.count("@x") == 3


async def test_search_round_trips_query():
    hits = [Post("at://X", "cidX", "carol", "kubectl tip", "2026-05-13")]
    fake = FakeBlueskyClient(search_results={"k8s": hits})
    tools = build_tools(_factory(fake))
    text = (await _tool(tools, "search").handler({"query": "k8s", "limit": 20}))["content"][0][
        "text"
    ]
    assert "@carol" in text
    assert "kubectl tip" in text


async def test_post_records_text_and_returns_uri():
    fake = FakeBlueskyClient()
    tools = build_tools(_factory(fake))
    text = (await _tool(tools, "post").handler({"text": "hello bluesky"}))["content"][0]["text"]
    assert "Posted: at://" in text
    assert fake.posted == ["hello bluesky"]


async def test_post_rejects_over_300_chars():
    fake = FakeBlueskyClient()
    tools = build_tools(_factory(fake))
    long = "x" * 301
    result = await _tool(tools, "post").handler({"text": long})
    assert result["is_error"] is True
    assert "300" in result["content"][0]["text"]
    assert fake.posted == []


async def test_reply_records_parent_refs():
    fake = FakeBlueskyClient()
    tools = build_tools(_factory(fake))
    result = await _tool(tools, "reply").handler(
        {"parent_uri": "at://abc", "parent_cid": "cid-abc", "text": "agree!"}
    )
    assert "Replied: at://" in result["content"][0]["text"]
    assert fake.replies == [("at://abc", "cid-abc", "agree!")]


async def test_reply_rejects_over_300_chars():
    fake = FakeBlueskyClient()
    tools = build_tools(_factory(fake))
    long = "x" * 301
    result = await _tool(tools, "reply").handler(
        {"parent_uri": "at://abc", "parent_cid": "cid-abc", "text": long}
    )
    assert result["is_error"] is True
    assert fake.replies == []


async def test_factory_failure_surfaces_as_tool_error():
    def boom():
        raise RuntimeError("BLUESKY_HANDLE / BLUESKY_APP_PASSWORD not set")

    tools = build_tools(boom)
    result = await _tool(tools, "timeline").handler({"limit": 10})
    assert result["is_error"] is True
    assert "Bluesky unavailable" in result["content"][0]["text"]


def test_build_server_names_server_bluesky():
    server = build_server(_factory(FakeBlueskyClient()))
    assert server["name"] == "bluesky"
    assert server["type"] == "sdk"


def test_client_from_env_missing_creds_raises(monkeypatch):
    monkeypatch.delenv("BLUESKY_HANDLE", raising=False)
    monkeypatch.delenv("BLUESKY_APP_PASSWORD", raising=False)
    with pytest.raises(RuntimeError, match="BLUESKY_HANDLE"):
        BlueskyClient.from_env()
