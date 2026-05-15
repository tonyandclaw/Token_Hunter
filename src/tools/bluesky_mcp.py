"""Bluesky MCP server — atproto SDK wrapped as four MCP tools.

  mcp__bluesky__timeline(limit)            Tier 1 (read; auto-forensic per post)
  mcp__bluesky__search(query, limit)       Tier 1 (read; auto-forensic per post)
  mcp__bluesky__post(text)                 Tier 2 → Telegram inline-confirm
  mcp__bluesky__reply(parent_uri, parent_cid, text)   Tier 2

Same shape as src/tools/gmail_mcp.py: BlueskyClient is the production
implementation (atproto.Client), BlueskyClientProtocol lets tests inject a
stub, build_tools(client_factory) closure-captures the factory so tests
can swap implementations without touching atproto.

Forensic auto-scan parallels gmail_mcp's: every fetched post runs through
`scan_post_for_injection` which calls forensic.analyze on (author_handle,
text). Warning+ findings append to logs/forensic.jsonl with source
"bluesky__feed"; info-level findings are skipped to keep the log compact
(timelines may return many posts).

Called by: src/agent.py:build_options → mcp_servers["bluesky"] = build_server().
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Protocol

from src import forensic, forensic_log
from src.audit import sha256_short

# claude_agent_sdk is imported lazily inside build_tools / build_server.
# Keeping it out of module scope means the pure helpers (Post,
# scan_post_for_injection, _format_posts) are unit-testable without the
# SDK installed.


@dataclass(frozen=True)
class Post:
    uri: str
    cid: str
    author: str
    text: str
    created_at: str


class BlueskyClientProtocol(Protocol):
    def timeline(self, limit: int) -> list[Post]: ...
    def search(self, query: str, limit: int) -> list[Post]: ...
    def post(self, text: str) -> Post: ...
    def reply(self, parent_uri: str, parent_cid: str, text: str) -> Post: ...


class BlueskyClient:
    """Default implementation backed by atproto.Client."""

    def __init__(self, handle: str, app_password: str):
        self.handle = handle
        self._app_password = app_password
        self._client: Any | None = None  # lazily logged in

    @classmethod
    def from_env(cls) -> BlueskyClient:
        handle = os.environ.get("BLUESKY_HANDLE")
        password = os.environ.get("BLUESKY_APP_PASSWORD")
        if not handle or not password:
            raise RuntimeError("BLUESKY_HANDLE / BLUESKY_APP_PASSWORD not set")
        return cls(handle=handle, app_password=password)

    def _login(self) -> Any:
        if self._client is None:
            from atproto import Client

            c = Client()
            c.login(self.handle, self._app_password)
            self._client = c
        return self._client

    @staticmethod
    def _post_from_view(view: Any) -> Post:
        rec = view.post if hasattr(view, "post") else view
        record = rec.record
        return Post(
            uri=str(rec.uri),
            cid=str(rec.cid),
            author=str(rec.author.handle),
            text=str(getattr(record, "text", "")),
            created_at=str(getattr(record, "created_at", "")),
        )

    def timeline(self, limit: int) -> list[Post]:
        client = self._login()
        resp = client.get_timeline(limit=limit)
        return [self._post_from_view(item) for item in resp.feed]

    def search(self, query: str, limit: int) -> list[Post]:
        client = self._login()
        resp = client.app.bsky.feed.search_posts({"q": query, "limit": limit})
        return [self._post_from_view(p) for p in resp.posts]

    def post(self, text: str) -> Post:
        client = self._login()
        resp = client.send_post(text=text)
        return Post(
            uri=str(resp.uri),
            cid=str(resp.cid),
            author=self.handle,
            text=text,
            created_at="",  # server timestamp not returned by send_post
        )

    def reply(self, parent_uri: str, parent_cid: str, text: str) -> Post:
        from atproto import models

        client = self._login()
        ref = models.AppBskyFeedPost.ReplyRef(
            parent=models.ComAtprotoRepoStrongRef.Main(uri=parent_uri, cid=parent_cid),
            root=models.ComAtprotoRepoStrongRef.Main(uri=parent_uri, cid=parent_cid),
        )
        resp = client.send_post(text=text, reply_to=ref)
        return Post(
            uri=str(resp.uri),
            cid=str(resp.cid),
            author=self.handle,
            text=text,
            created_at="",
        )


def _author_domain(handle: str) -> str:
    """Bluesky handles look like `alice.bsky.social` or `acme.com` — strip @."""
    h = handle.lstrip("@").strip().lower()
    return h


def scan_post_for_injection(post: Post) -> forensic.ForensicReport:
    """Run forensic.analyze on a single Bluesky post; record warning+ findings.

    Posts are public and untrusted, just like incoming email bodies. We scan
    the text body against the injection-pattern DB. Domain Levenshtein vs
    the trusted list is run on the author handle (so `asus.com` would match
    the trusted entry, `asu5.com` would not). Findings of severity warning+
    are appended to logs/forensic.jsonl so /status and the CLI can surface
    them; info-level scans are skipped to keep the log compact (the timeline
    scans potentially many posts).

    Called by: build_tools().timeline and build_tools().search below, on
    every fetched post.
    """
    report = forensic.analyze(_author_domain(post.author), post.text)
    if report.severity != "info":
        forensic_log.record(
            report,
            source="bluesky__feed",
            body_hash=sha256_short(post.text),
            extra={"uri": post.uri, "author": post.author},
        )
    return report


def _format_posts(posts: list[Post]) -> str:
    if not posts:
        return "(沒有符合條件的貼文)"
    lines = []
    warnings: list[str] = []
    for p in posts:
        report = scan_post_for_injection(p)
        icon = ""
        if report.severity == "warning":
            icon = " ⚠️"
        elif report.severity == "block":
            icon = " 🚨"
            warnings.append(f"@{p.author}: {','.join(report.injection_hits) or 'typosquat'}")
        lines.append(f"- @{p.author}{icon} | {p.created_at}")
        lines.append(f"  {p.text.strip()[:280]}")
        lines.append(f"  uri: {p.uri}  cid: {p.cid}")
    if warnings:
        lines.append("")
        lines.append("🚨 Forensic 警示 (block 等級):")
        for w in warnings:
            lines.append(f"  • {w}")
    return "\n".join(lines)


def build_tools(client_factory):
    from claude_agent_sdk import tool

    def _client_or_error() -> tuple[BlueskyClientProtocol | None, dict | None]:
        try:
            return client_factory(), None
        except Exception as e:  # noqa: BLE001
            return None, {
                "content": [{"type": "text", "text": f"Bluesky unavailable: {e}"}],
                "is_error": True,
            }

    @tool(
        "timeline",
        "Get the most recent posts from your Bluesky home timeline.",
        {"limit": int},
    )
    async def timeline(args: dict) -> dict:
        client, err = _client_or_error()
        if err:
            return err
        posts = client.timeline(int(args.get("limit", 20)))
        return {"content": [{"type": "text", "text": _format_posts(posts)}]}

    @tool(
        "search",
        "Search Bluesky posts by free-text query.",
        {"query": str, "limit": int},
    )
    async def search(args: dict) -> dict:
        client, err = _client_or_error()
        if err:
            return err
        posts = client.search(str(args["query"]), int(args.get("limit", 20)))
        return {"content": [{"type": "text", "text": _format_posts(posts)}]}

    @tool(
        "post",
        "Post to Bluesky as the user. Tier 2 — confirmation required.",
        {"text": str},
    )
    async def post(args: dict) -> dict:
        client, err = _client_or_error()
        if err:
            return err
        text = str(args["text"])
        if len(text) > 300:
            return {
                "content": [
                    {"type": "text", "text": f"Bluesky post limit is 300 chars (got {len(text)})"}
                ],
                "is_error": True,
            }
        p = client.post(text)
        return {"content": [{"type": "text", "text": f"Posted: {p.uri}"}]}

    @tool(
        "reply",
        "Reply to a Bluesky post. Tier 2 — confirmation required. "
        "parent_uri and parent_cid identify the post being replied to.",
        {"parent_uri": str, "parent_cid": str, "text": str},
    )
    async def reply(args: dict) -> dict:
        client, err = _client_or_error()
        if err:
            return err
        text = str(args["text"])
        if len(text) > 300:
            return {
                "content": [
                    {"type": "text", "text": f"Bluesky post limit is 300 chars (got {len(text)})"}
                ],
                "is_error": True,
            }
        p = client.reply(str(args["parent_uri"]), str(args["parent_cid"]), text)
        return {"content": [{"type": "text", "text": f"Replied: {p.uri}"}]}

    return [timeline, search, post, reply]


def build_server(client_factory=BlueskyClient.from_env) -> Any:
    from claude_agent_sdk import create_sdk_mcp_server

    return create_sdk_mcp_server(name="bluesky", version="0.1.0", tools=build_tools(client_factory))
