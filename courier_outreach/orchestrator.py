"""The orchestrator — one cycle of the pipeline, plus a small CLI.

A cycle (run every ~15 min by a systemd timer on the VPS):
  1. read replies over IMAP (known senders only) and classify them;
  2. send any due first-touch / follow-up emails, within the warm-up cap and
     send window;
  3. push the leads table to the Google Sheet.

Sourcing is heavier, so it runs on its own (the `source` command, e.g. once a
day). Everything is idempotent, so a missed or double run is harmless.
"""

from __future__ import annotations

import argparse
import logging
import random
import sqlite3
import time
from datetime import datetime, timedelta, timezone

from . import db
from .config import Config, ImapConfig, SendingPolicy, SmtpConfig
from .mail import sender
from .mail.governor import WarmupGovernor
from .mail.reader import InboundReply, read_replies
from .models import LeadStatus, MessageDirection
from .templates import render, template_for_status
from .triage import classify_reply, suggested_status

log = logging.getLogger(__name__)

# name of template -> the status the lead moves to once it's sent
_ADVANCE = {
    "first_touch": LeadStatus.SENT,
    "followup_1": LeadStatus.FOLLOWUP_1,
    "followup_2": LeadStatus.FOLLOWUP_2,
}


# --------------------------------------------------------------------------- #
# Selecting who to email
# --------------------------------------------------------------------------- #
def _has_email(row: sqlite3.Row) -> bool:
    return bool(row["contact_email"])


def select_due_leads(conn: sqlite3.Connection, policy: SendingPolicy,
                     now_utc: datetime) -> list[sqlite3.Row]:
    """Follow-ups that are due (first), then fresh first-touch leads. Both need
    an email address. Follow-up gaps are measured from the previous email."""
    gaps = policy.followup_days or []
    gap1 = gaps[0] if len(gaps) >= 1 else None
    gap2 = gaps[1] if len(gaps) >= 2 else None

    def due_since(row, gap_days):
        if gap_days is None or not row["last_email_at"]:
            return False
        try:
            last = datetime.fromisoformat(row["last_email_at"])
        except ValueError:
            return False
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        return last <= now_utc - timedelta(days=gap_days)

    followups: list[sqlite3.Row] = []
    for row in conn.execute("SELECT * FROM leads WHERE status = ?",
                            (LeadStatus.SENT.value,)).fetchall():
        if _has_email(row) and due_since(row, gap1):
            followups.append(row)
    for row in conn.execute("SELECT * FROM leads WHERE status = ?",
                            (LeadStatus.FOLLOWUP_1.value,)).fetchall():
        if _has_email(row) and due_since(row, gap2):
            followups.append(row)

    fresh = [r for r in conn.execute(
        "SELECT * FROM leads WHERE status IN (?,?) ORDER BY id",
        (LeadStatus.NEW.value, LeadStatus.QUEUED.value)).fetchall()
        if _has_email(r)]

    return followups + fresh


# --------------------------------------------------------------------------- #
# Sending
# --------------------------------------------------------------------------- #
def send_due(config: Config, smtp_config: SmtpConfig, conn: sqlite3.Connection,
             now: datetime | None = None, jitter: tuple[float, float] = (1.0, 4.0),
             send_fn=None) -> int:
    """Send due emails within the warm-up cap and the send window. Returns the
    number sent."""
    gov = WarmupGovernor(config.policy, config.booking.timezone)
    now = now or gov.local_now()
    if not gov.in_send_window(now):
        log.info("outside send window; skipping send")
        return 0
    remaining = gov.remaining_today(conn, now)
    if remaining <= 0:
        log.info("daily warm-up cap reached; skipping send")
        return 0

    now_utc = now.astimezone(timezone.utc) if now.tzinfo else now.replace(
        tzinfo=timezone.utc)
    send = send_fn or sender.send_email
    sent = 0
    for lead in select_due_leads(conn, config.policy, now_utc):
        if sent >= remaining:
            break
        name = template_for_status(LeadStatus(lead["status"]))
        if not name:
            continue
        email = render(name, lead, config.business)
        try:
            mid = send(smtp_config, lead["contact_email"], email.subject,
                       email.body_text)
        except Exception as err:
            log.warning("send to %s failed: %s", lead["contact_email"], err)
            continue

        db.record_message(conn, int(lead["id"]), MessageDirection.OUTBOUND,
                          email.subject, email.body_text, message_id=mid)
        db.set_status(conn, int(lead["id"]), _ADVANCE[name],
                      last_email_at=now_utc.isoformat())
        gov.record_sent(conn, 1, now)
        sent += 1
        if jitter:
            time.sleep(random.uniform(*jitter))
    log.info("send_due: sent %d (cap remaining was %d)", sent, remaining)
    return sent


# --------------------------------------------------------------------------- #
# Replies
# --------------------------------------------------------------------------- #
def handle_replies(conn: sqlite3.Connection,
                   replies: list[InboundReply]) -> dict[str, int]:
    """Classify each new reply, tag the stored message, and move the lead's
    status. Unsubscribes suppress the lead automatically."""
    counts: dict[str, int] = {}
    for reply in replies:
        cls = classify_reply(reply.body)
        counts[cls.value] = counts.get(cls.value, 0) + 1
        if reply.message_id:
            conn.execute("UPDATE messages SET reply_class = ? WHERE message_id = ?",
                         (cls.value, reply.message_id))
            conn.commit()
        new_status = suggested_status(cls)
        if new_status is not None:
            db.set_status(conn, reply.lead_id, new_status,
                          reply_summary=(reply.body or "")[:250])
    if counts:
        log.info("handle_replies: %s", counts)
    return counts


# --------------------------------------------------------------------------- #
# One full cycle
# --------------------------------------------------------------------------- #
def run_cycle(config: Config, smtp_config: SmtpConfig, imap_config: ImapConfig,
              conn: sqlite3.Connection) -> None:
    # 1. replies
    try:
        replies = read_replies(conn, imap_config)
        handle_replies(conn, replies)
    except Exception:
        log.exception("reply step failed")
    # 2. send
    try:
        send_due(config, smtp_config, conn)
    except Exception:
        log.exception("send step failed")
    # 3. sheet sync
    try:
        from .cockpit import sheets
        sheets.push(config, conn)
    except Exception:
        log.exception("sheet sync failed (leads still safe in the DB)")


def run_sources(config: Config, conn: sqlite3.Connection,
                csv_path: str | None = None) -> None:
    from .sourcing.ingest import ingest
    from .sourcing.osm import OverpassSource

    total = ingest(conn, OverpassSource())
    log.info("OSM sourcing: %s", total)
    if csv_path:
        from .sourcing.csv_import import CsvImportSource
        log.info("CSV sourcing: %s", ingest(conn, CsvImportSource(csv_path)))


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="courier_outreach")
    parser.add_argument("command",
                        choices=["run", "source", "send", "read", "sync",
                                 "init-db", "serve"])
    parser.add_argument("--csv", help="seed CSV path for the `source` command")
    args = parser.parse_args(argv)

    config = Config.load()
    logging.basicConfig(level=getattr(logging, config.log_level, logging.INFO),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    conn = db.connect(config.database_path)
    db.init_db(conn)

    if args.command == "init-db":
        print(f"DB ready at {config.database_path}")
        return 0
    if args.command == "serve":
        import uvicorn
        from .app.server import build_default_app
        uvicorn.run(build_default_app(), host=config.app_host, port=config.app_port)
        return 0
    if args.command == "source":
        run_sources(config, conn, args.csv)
        return 0
    if args.command == "read":
        handle_replies(conn, read_replies(conn, ImapConfig.load()))
        return 0
    if args.command == "send":
        send_due(config, SmtpConfig.load(), conn)
        return 0
    if args.command == "sync":
        from .cockpit import sheets
        print(f"synced {sheets.push(config, conn)} leads")
        return 0
    if args.command == "run":
        run_cycle(config, SmtpConfig.load(), ImapConfig.load(), conn)
        return 0
    return 1
