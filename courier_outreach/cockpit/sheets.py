"""Push the leads table to a Google Sheet — your at-a-glance cockpit.

Strategy: a full refresh each sync (clear the tab, write header + every lead).
Simple and correct for the volumes here; the SQLite DB remains the source of
truth, the Sheet is a read-friendly mirror you can browse on your phone.
"""

from __future__ import annotations

import sqlite3
from typing import Mapping, Sequence

from ..config import Config
from ..models import SHEET_COLUMNS
from .clients import build_sheets_service

# DB column for each Sheet column, in the same order as SHEET_COLUMNS.
_ROW_FIELDS = [
    "company", "area", "industry", "website", "contact_email", "contact_name",
    "phone", "status", "last_email_at", "next_action_at", "reply_summary",
    "meeting_time", "source", "notes",
]


def _cell(lead: Mapping, key: str) -> str:
    try:
        value = lead[key]
    except (KeyError, IndexError):
        value = None
    return "" if value is None else str(value)


def lead_to_row(lead: Mapping) -> list[str]:
    return [_cell(lead, f) for f in _ROW_FIELDS]


def build_values(leads: Sequence[Mapping]) -> list[list[str]]:
    return [list(SHEET_COLUMNS)] + [lead_to_row(l) for l in leads]


def _first_sheet_title(service, spreadsheet_id: str) -> str:
    meta = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    return meta["sheets"][0]["properties"]["title"]


def sync_leads(service, spreadsheet_id: str, leads: Sequence[Mapping],
               sheet_name: str | None = None) -> int:
    """Overwrite the sheet tab with the current leads. Returns lead count."""
    if sheet_name is None:
        sheet_name = _first_sheet_title(service, spreadsheet_id)
    values = build_values(leads)
    service.spreadsheets().values().clear(
        spreadsheetId=spreadsheet_id, range=sheet_name, body={}).execute()
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id, range=f"{sheet_name}!A1",
        valueInputOption="RAW", body={"values": values}).execute()
    return len(leads)


def push(config: Config, conn: sqlite3.Connection) -> int:
    """High-level: connect and sync every lead to the configured Sheet."""
    service = build_sheets_service(config)
    leads = conn.execute("SELECT * FROM leads ORDER BY id").fetchall()
    return sync_leads(service, config.google_sheet_id, leads)
