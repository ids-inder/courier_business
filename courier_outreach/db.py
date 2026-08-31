"""SQLite persistence — the machine's source of truth.

Why a local DB when the Google Sheet is the cockpit? Because the pipeline needs
things a Sheet can't safely give: idempotent de-duplication, an exact send log
for the warm-up accounting, and atomic status transitions. The Sheet is a
projection we push to for the human; this is what the code reasons over.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .models import LeadStatus, MessageDirection

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    company         TEXT NOT NULL,
    area            TEXT,                 -- 'Tricity' | 'Baddi'
    industry        TEXT,
    website         TEXT,
    contact_email   TEXT,
    contact_name    TEXT,
    phone           TEXT,
    source          TEXT,                 -- how we found them
    status          TEXT NOT NULL DEFAULT 'new',
    reply_summary   TEXT,
    meeting_time    TEXT,                 -- ISO8601 once booked
    notes           TEXT,
    last_email_at   TEXT,
    next_action_at  TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

-- De-dupe keys. A company is unique by email when we have one, else by
-- (company, area). Partial unique indexes enforce both without collisions.
CREATE UNIQUE INDEX IF NOT EXISTS idx_leads_email
    ON leads(contact_email) WHERE contact_email IS NOT NULL AND contact_email != '';
CREATE UNIQUE INDEX IF NOT EXISTS idx_leads_company_area
    ON leads(company, area) WHERE contact_email IS NULL OR contact_email = '';
CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status);

CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id         INTEGER NOT NULL REFERENCES leads(id),
    direction       TEXT NOT NULL,        -- 'outbound' | 'inbound'
    subject         TEXT,
    body            TEXT,
    message_id      TEXT,                 -- RFC822 Message-ID (for threading)
    in_reply_to     TEXT,
    reply_class     TEXT,                 -- set on inbound after classification
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_lead ON messages(lead_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_msgid
    ON messages(message_id) WHERE message_id IS NOT NULL AND message_id != '';

-- One row per calendar day: how many outreach emails we've sent. The warm-up
-- governor reads/writes this to enforce the daily cap.
CREATE TABLE IF NOT EXISTS send_budget (
    day             TEXT PRIMARY KEY,     -- 'YYYY-MM-DD' (local)
    sent_count      INTEGER NOT NULL DEFAULT 0
);

-- Append-only audit trail of everything the agent does, for debugging + trust.
CREATE TABLE IF NOT EXISTS audit (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id         INTEGER,
    event           TEXT NOT NULL,
    detail          TEXT,
    created_at      TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect(database_path: Path) -> sqlite3.Connection:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(database_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


# --- Leads ------------------------------------------------------------------

def find_existing(conn: sqlite3.Connection, company: str, area: str | None,
                  email: str | None) -> sqlite3.Row | None:
    """The de-dupe rule, in one place: match by email if we have one, else by
    (company, area). Returns the existing lead row, or None.
    """
    email = (email or "").strip().lower() or None
    if email:
        row = conn.execute(
            "SELECT * FROM leads WHERE lower(contact_email) = ?", (email,)
        ).fetchone()
        if row is not None:
            return row
    return conn.execute(
        "SELECT * FROM leads WHERE company = ? AND IFNULL(area,'') = IFNULL(?,'')",
        (company.strip(), (area or "").strip() or None),
    ).fetchone()


def upsert_lead(conn: sqlite3.Connection, **fields) -> int:
    """Insert a discovered lead, or return the existing id if we already have
    it (matched by email, else by company+area). Never creates a duplicate.
    Returns the lead id.
    """
    email = (fields.get("contact_email") or "").strip().lower() or None
    company = fields["company"].strip()
    area = (fields.get("area") or "").strip() or None

    existing = find_existing(conn, company, area, email)
    if existing is not None:
        return int(existing["id"])

    now = _now()
    cur = conn.execute(
        """INSERT INTO leads
           (company, area, industry, website, contact_email, contact_name,
            phone, source, status, notes, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            company, area, fields.get("industry"), fields.get("website"),
            email, fields.get("contact_name"), fields.get("phone"),
            fields.get("source"), LeadStatus.NEW.value, fields.get("notes"),
            now, now,
        ),
    )
    conn.commit()
    audit(conn, cur.lastrowid, "lead_created", f"{company} via {fields.get('source')}")
    return int(cur.lastrowid)


def set_status(conn: sqlite3.Connection, lead_id: int, status: LeadStatus,
               **extra) -> None:
    cols = ["status = ?", "updated_at = ?"]
    vals: list = [status.value, _now()]
    for key in ("reply_summary", "meeting_time", "last_email_at",
                "next_action_at", "notes", "contact_email", "contact_name"):
        if key in extra:
            cols.append(f"{key} = ?")
            vals.append(extra[key])
    vals.append(lead_id)
    conn.execute(f"UPDATE leads SET {', '.join(cols)} WHERE id = ?", vals)
    conn.commit()
    audit(conn, lead_id, "status_change", status.value)


def get_lead(conn: sqlite3.Connection, lead_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()


def leads_by_status(conn: sqlite3.Connection, status: LeadStatus) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM leads WHERE status = ? ORDER BY id", (status.value,)
    ).fetchall()


def find_lead_by_email(conn: sqlite3.Connection, email: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM leads WHERE lower(contact_email) = ?",
        (email.strip().lower(),),
    ).fetchone()


# --- Messages ---------------------------------------------------------------

def record_message(conn: sqlite3.Connection, lead_id: int,
                   direction: MessageDirection, subject: str | None,
                   body: str | None, message_id: str | None = None,
                   in_reply_to: str | None = None,
                   reply_class: str | None = None) -> int:
    cur = conn.execute(
        """INSERT INTO messages
           (lead_id, direction, subject, body, message_id, in_reply_to,
            reply_class, created_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (lead_id, direction.value, subject, body, message_id, in_reply_to,
         reply_class, _now()),
    )
    conn.commit()
    return int(cur.lastrowid)


def message_exists(conn: sqlite3.Connection, message_id: str) -> bool:
    if not message_id:
        return False
    row = conn.execute(
        "SELECT 1 FROM messages WHERE message_id = ?", (message_id,)
    ).fetchone()
    return row is not None


# --- Send budget (warm-up accounting) ---------------------------------------

def sent_today(conn: sqlite3.Connection, day: str) -> int:
    row = conn.execute(
        "SELECT sent_count FROM send_budget WHERE day = ?", (day,)
    ).fetchone()
    return int(row["sent_count"]) if row else 0


def increment_sent(conn: sqlite3.Connection, day: str, by: int = 1) -> None:
    conn.execute(
        """INSERT INTO send_budget (day, sent_count) VALUES (?, ?)
           ON CONFLICT(day) DO UPDATE SET sent_count = sent_count + ?""",
        (day, by, by),
    )
    conn.commit()


def first_active_day(conn: sqlite3.Connection) -> str | None:
    """The earliest day we ever sent — anchors the warm-up ramp."""
    row = conn.execute("SELECT MIN(day) AS d FROM send_budget").fetchone()
    return row["d"] if row and row["d"] else None


# --- Audit ------------------------------------------------------------------

def audit(conn: sqlite3.Connection, lead_id: int | None, event: str,
          detail: str | None = None) -> None:
    conn.execute(
        "INSERT INTO audit (lead_id, event, detail, created_at) VALUES (?,?,?,?)",
        (lead_id, event, detail, _now()),
    )
    conn.commit()
