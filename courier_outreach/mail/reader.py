"""Read replies over IMAP — and ONLY from companies we emailed.

Privacy rule (non-negotiable): a message is looked at only if its sender is a
lead already in our DB. Every other message in the mailbox is skipped and never
read, parsed, stored, or shown. We also open the mailbox READ-ONLY, so we never
change flags or move mail around in the operator's inbox.

This module only *ingests* replies (parse + store + link to the lead). Deciding
whether a reply is positive/negative/unsubscribe is the triage module's job.
"""

from __future__ import annotations

import email
import imaplib
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.policy import default as default_policy
from email.utils import parseaddr

from bs4 import BeautifulSoup

from .. import db
from ..config import ImapConfig
from ..models import MessageDirection

log = logging.getLogger(__name__)


@dataclass
class ParsedEmail:
    from_addr: str
    subject: str
    body: str
    message_id: str | None
    in_reply_to: str | None


@dataclass
class InboundReply:
    lead_id: int
    from_addr: str
    subject: str
    body: str
    message_id: str | None


def _extract_body(msg: email.message.EmailMessage) -> str:
    """Best-effort plain-text body. Prefers text/plain; falls back to stripping
    a text/html part."""
    if msg.is_multipart():
        # First a real text/plain part.
        for part in msg.walk():
            if (part.get_content_type() == "text/plain"
                    and "attachment" not in str(part.get("Content-Disposition", ""))):
                try:
                    return part.get_content().strip()
                except Exception:
                    continue
        # Otherwise, the first text/html, de-tagged.
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                try:
                    return BeautifulSoup(part.get_content(), "lxml").get_text(
                        " ", strip=True)
                except Exception:
                    continue
        return ""
    try:
        content = msg.get_content()
    except Exception:
        return ""
    if msg.get_content_type() == "text/html":
        return BeautifulSoup(content, "lxml").get_text(" ", strip=True)
    return (content or "").strip()


def parse_email(raw: bytes) -> ParsedEmail:
    msg = email.message_from_bytes(raw, policy=default_policy)
    _, from_addr = parseaddr(msg.get("From", ""))
    return ParsedEmail(
        from_addr=(from_addr or "").strip().lower(),
        subject=(msg.get("Subject", "") or "").strip(),
        body=_extract_body(msg),
        message_id=(msg.get("Message-ID") or "").strip() or None,
        in_reply_to=(msg.get("In-Reply-To") or "").strip() or None,
    )


def process_replies(conn: sqlite3.Connection,
                    raw_messages: list[bytes]) -> list[InboundReply]:
    """Pure ingest logic (no network): parse each raw message, keep only those
    from known leads, de-dupe by Message-ID, store, and return the new ones.
    """
    new_replies: list[InboundReply] = []
    for raw in raw_messages:
        try:
            parsed = parse_email(raw)
        except Exception as err:
            log.warning("failed to parse a message: %s", err)
            continue

        if not parsed.from_addr:
            continue

        # PRIVACY GATE: only known leads. Unknown senders are dropped entirely.
        lead = db.find_lead_by_email(conn, parsed.from_addr)
        if lead is None:
            continue

        # Idempotency: don't act on the same message twice.
        if parsed.message_id and db.message_exists(conn, parsed.message_id):
            continue

        db.record_message(
            conn, int(lead["id"]), MessageDirection.INBOUND,
            subject=parsed.subject, body=parsed.body,
            message_id=parsed.message_id, in_reply_to=parsed.in_reply_to,
        )
        db.audit(conn, int(lead["id"]), "reply_received", parsed.from_addr)
        new_replies.append(InboundReply(
            lead_id=int(lead["id"]), from_addr=parsed.from_addr,
            subject=parsed.subject, body=parsed.body,
            message_id=parsed.message_id,
        ))
    return new_replies


class ImapReader:
    """Fetches recent raw messages over IMAP (read-only)."""

    def __init__(self, cfg: ImapConfig):
        self.cfg = cfg

    def fetch_raw_since(self, since_days: int = 14) -> list[bytes]:
        conn = imaplib.IMAP4_SSL(self.cfg.host, self.cfg.port)
        try:
            conn.login(self.cfg.username, self.cfg.password)
            # readonly=True => we never set \Seen or otherwise mutate the mailbox
            conn.select(self.cfg.mailbox, readonly=True)
            since = (datetime.utcnow() - timedelta(days=since_days)).strftime("%d-%b-%Y")
            typ, data = conn.search(None, f'(SINCE {since})')
            if typ != "OK" or not data or not data[0]:
                return []
            raws: list[bytes] = []
            for num in data[0].split():
                # BODY.PEEK[] fetches without setting the \Seen flag.
                typ, msg_data = conn.fetch(num, "(BODY.PEEK[])")
                if typ != "OK":
                    continue
                for part in msg_data:
                    if isinstance(part, tuple) and part[1]:
                        raws.append(part[1])
            return raws
        finally:
            try:
                conn.logout()
            except Exception:
                pass


def read_replies(conn: sqlite3.Connection, cfg: ImapConfig,
                 since_days: int = 14) -> list[InboundReply]:
    """Fetch recent mail and ingest replies from known leads only."""
    raws = ImapReader(cfg).fetch_raw_since(since_days)
    replies = process_replies(conn, raws)
    log.info("read_replies: %d fetched, %d new from known leads",
             len(raws), len(replies))
    return replies
