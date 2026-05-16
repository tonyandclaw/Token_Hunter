"""Gmail MCP server — IMAP read + SMTP send via app password.

Per docs/01 §4: explicit demo simplification, we use IMAP + an app password
instead of OAuth so the demo doesn't blow time on consent screens.

Four tools, all exposed via `mcp__gmail__*`:
  - `mcp__gmail__list_unread(limit)`  — Tier 1 (read)
  - `mcp__gmail__search(query, limit)` — Tier 1 (read; Gmail-style query)
  - `mcp__gmail__read(uid)`           — Tier 1 (read full body of one message)
  - `mcp__gmail__send(to, subject, body)` — Tier 2 (external write → confirm)

GmailClient is a thin facade so tests can inject a mock without touching
imap-tools / smtplib. The SDK-side tool functions just translate args to
client method calls and shape the result for Claude.
"""

from __future__ import annotations

import os
import re
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Any, Protocol

from claude_agent_sdk import create_sdk_mcp_server, tool

from src.forensic import analyze as analyze_forensic


@dataclass(frozen=True)
class EmailSummary:
    uid: str
    sender: str
    subject: str
    date: str  # RFC 2822 string from IMAP; agent re-parses if needed
    snippet: str


@dataclass(frozen=True)
class EmailFull:
    uid: str
    sender: str
    to: tuple[str, ...]
    subject: str
    date: str
    body: str
    attachments: tuple[str, ...]


class GmailClientProtocol(Protocol):
    def list_unread(self, limit: int) -> list[EmailSummary]: ...
    def search(self, query: str, limit: int) -> list[EmailSummary]: ...
    def read(self, uid: str) -> EmailFull | None: ...
    def send(self, to: str, subject: str, body: str) -> str: ...


class GmailClient:
    """Default IMAP/SMTP implementation using imap-tools + stdlib smtplib."""

    def __init__(
        self,
        address: str,
        app_password: str,
        *,
        imap_host: str = "imap.gmail.com",
        smtp_host: str = "smtp.gmail.com",
        smtp_port: int = 465,
    ):
        self.address = address
        self._app_password = app_password
        self.imap_host = imap_host
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port

    @classmethod
    def from_env(cls) -> GmailClient:
        addr = os.environ.get("GMAIL_ADDRESS")
        pwd = os.environ.get("GMAIL_APP_PASSWORD")
        if not addr or not pwd:
            raise RuntimeError("GMAIL_ADDRESS / GMAIL_APP_PASSWORD not set")
        return cls(
            address=addr,
            app_password=pwd,
            imap_host=os.environ.get("GMAIL_IMAP_HOST", "imap.gmail.com"),
            smtp_host=os.environ.get("GMAIL_SMTP_HOST", "smtp.gmail.com"),
        )

    def _mailbox(self):
        from imap_tools import MailBox

        return MailBox(self.imap_host).login(self.address, self._app_password)

    @staticmethod
    def _summary(msg) -> EmailSummary:
        # Snippet: first 200 chars of plain-text body, single-line
        body = (msg.text or msg.html or "").strip()
        snippet = " ".join(body.split())[:200]
        return EmailSummary(
            uid=str(msg.uid),
            sender=str(msg.from_),
            subject=msg.subject or "",
            date=msg.date_str or "",
            snippet=snippet,
        )

    def list_unread(self, limit: int) -> list[EmailSummary]:
        from imap_tools import AND

        with self._mailbox() as mb:
            return [
                self._summary(m) for m in mb.fetch(AND(seen=False), limit=limit, mark_seen=False)
            ]

    def search(self, query: str, limit: int) -> list[EmailSummary]:
        # Gmail-style search via the X-GM-RAW IMAP extension
        with self._mailbox() as mb:
            return [
                self._summary(m)
                for m in mb.fetch(f'X-GM-RAW "{query}"', limit=limit, mark_seen=False)
            ]

    def read(self, uid: str) -> EmailFull | None:
        with self._mailbox() as mb:
            msgs = list(mb.fetch(f"UID {uid}", limit=1, mark_seen=False))
            if not msgs:
                return None
            m = msgs[0]
            return EmailFull(
                uid=str(m.uid),
                sender=str(m.from_),
                to=tuple(m.to or ()),
                subject=m.subject or "",
                date=m.date_str or "",
                body=(m.text or m.html or "").strip(),
                attachments=tuple(a.filename or "(unnamed)" for a in (m.attachments or ())),
            )

    def send(self, to: str, subject: str, body: str) -> str:
        msg = EmailMessage()
        msg["From"] = self.address
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port) as smtp:
            smtp.login(self.address, self._app_password)
            smtp.send_message(msg)
        return "sent"


def _format_summaries(items: list[EmailSummary]) -> str:
    if not items:
        return "(沒有符合條件的信件)"
    lines = []
    for s in items:
        lines.append(f"- uid={s.uid} | {s.date} | {s.sender}")
        lines.append(f"  主旨: {s.subject}")
        if s.snippet:
            lines.append(f"  摘要: {s.snippet}")
    return "\n".join(lines)


_SENDER_ADDR_RE = re.compile(r"<([^>]+)>")


def _sender_domain(sender: str) -> str:
    """Extract bare domain from a From header like '"Alice" <alice@a.com>'."""
    m = _SENDER_ADDR_RE.search(sender)
    addr = m.group(1) if m else sender
    return addr.split("@")[-1].strip().lower() if "@" in addr else addr.strip().lower()


def _forensic_block_for(m: EmailFull) -> str | None:
    """Run the forensic analyzer; return a warning block only if severity != info.

    On a benign message we return None so the agent's context isn't polluted
    with empty forensic blocks. Tier-3 auto-block lives in permissions.py;
    this is the in-tool advisory layer the agent sees alongside the body.
    """
    domain = _sender_domain(m.sender)
    if not domain:
        return None
    report = analyze_forensic(domain, m.body)
    if report.severity == "info":
        return None
    return report.render()


def _format_full(m: EmailFull) -> str:
    body = (
        f"uid: {m.uid}\n"
        f"From: {m.sender}\n"
        f"To: {', '.join(m.to) if m.to else '(none)'}\n"
        f"Date: {m.date}\n"
        f"Subject: {m.subject}\n"
        f"Attachments: {', '.join(m.attachments) if m.attachments else '(none)'}\n\n"
        f"{m.body}"
    )
    forensic = _forensic_block_for(m)
    if forensic is not None:
        body = f"{body}\n\n---\n{forensic}"
    return body


def build_tools(client_factory):
    """Build the four SDK tools, each lazily resolving its client via client_factory.

    client_factory is called fresh on every tool invocation. In production
    that's GmailClient.from_env; in tests it returns a stub.
    """

    def _client_or_error(text: str | None = None) -> tuple[GmailClientProtocol | None, dict | None]:
        try:
            return client_factory(), None
        except Exception as e:  # noqa: BLE001 — surface any client init failure as tool error
            return None, {
                "content": [{"type": "text", "text": f"Gmail unavailable: {e}"}],
                "is_error": True,
            }

    @tool(
        "list_unread",
        "List unread emails in the user's inbox, most-recent first.",
        {"limit": int},
    )
    async def list_unread(args: dict) -> dict:
        client, err = _client_or_error()
        if err:
            return err
        items = client.list_unread(int(args.get("limit", 20)))
        return {"content": [{"type": "text", "text": _format_summaries(items)}]}

    @tool(
        "search",
        "Search emails using Gmail search syntax (e.g. 'from:alice@x is:unread').",
        {"query": str, "limit": int},
    )
    async def search(args: dict) -> dict:
        client, err = _client_or_error()
        if err:
            return err
        items = client.search(str(args["query"]), int(args.get("limit", 20)))
        return {"content": [{"type": "text", "text": _format_summaries(items)}]}

    @tool(
        "read",
        "Read one email by IMAP uid; returns headers, body, attachment filenames.",
        {"uid": str},
    )
    async def read(args: dict) -> dict:
        client, err = _client_or_error()
        if err:
            return err
        msg = client.read(str(args["uid"]))
        if msg is None:
            return {
                "content": [{"type": "text", "text": f"No message with uid={args['uid']}"}],
                "is_error": True,
            }
        return {"content": [{"type": "text", "text": _format_full(msg)}]}

    @tool(
        "send",
        "Send an email. Tier 2 — the user will be asked to confirm before this runs.",
        {"to": str, "subject": str, "body": str},
    )
    async def send(args: dict) -> dict:
        client, err = _client_or_error()
        if err:
            return err
        result = client.send(str(args["to"]), str(args["subject"]), str(args["body"]))
        return {"content": [{"type": "text", "text": f"Send result: {result}"}]}

    return [list_unread, search, read, send]


def build_server(client_factory=GmailClient.from_env) -> Any:
    """Build the in-process MCP server. Pass a stub factory for tests."""
    return create_sdk_mcp_server(name="gmail", version="0.1.0", tools=build_tools(client_factory))
