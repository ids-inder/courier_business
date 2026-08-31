"""The warm-up governor — the deliverability safety valve.

It answers one question: *may we send another outreach email right now, and how
many more today?* Two gates:

  1. The daily cap ramps up from a small number (WARMUP_START_PER_DAY) so a fresh
     sender builds reputation instead of tripping spam filters.
  2. Sends only happen inside a local-time window (SEND_WINDOW_*), so they land
     during business hours and look human.

Follow-ups and first-touch emails both count against the same daily cap.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore

from .. import db
from ..config import SendingPolicy


def _parse_hhmm(value: str) -> tuple[int, int]:
    h, m = value.split(":", 1)
    return int(h), int(m)


class WarmupGovernor:
    def __init__(self, policy: SendingPolicy, timezone: str = "Asia/Kolkata"):
        self.policy = policy
        self.timezone = timezone

    # --- time helpers (injectable `now` for testing) ------------------------
    def _tz(self):
        if ZoneInfo is None:
            return None
        try:
            return ZoneInfo(self.timezone)
        except Exception:
            return None

    def local_now(self, now: datetime | None = None) -> datetime:
        if now is not None:
            return now
        tz = self._tz()
        return datetime.now(tz) if tz else datetime.now()

    def today_str(self, now: datetime | None = None) -> str:
        return self.local_now(now).date().isoformat()

    # --- the ramp -----------------------------------------------------------
    def day_index(self, conn: sqlite3.Connection, now: datetime | None = None) -> int:
        """Days since the first day we ever sent (0 on day one)."""
        first = db.first_active_day(conn)
        if not first:
            return 0
        first_date = date.fromisoformat(first)
        return max(0, (self.local_now(now).date() - first_date).days)

    def cap_today(self, conn: sqlite3.Connection, now: datetime | None = None) -> int:
        return self.policy.cap_for_day(self.day_index(conn, now))

    def sent_today(self, conn: sqlite3.Connection, now: datetime | None = None) -> int:
        return db.sent_today(conn, self.today_str(now))

    def remaining_today(self, conn: sqlite3.Connection,
                        now: datetime | None = None) -> int:
        return max(0, self.cap_today(conn, now) - self.sent_today(conn, now))

    # --- the window ---------------------------------------------------------
    def in_send_window(self, now: datetime | None = None) -> bool:
        t = self.local_now(now).time()
        start_h, start_m = _parse_hhmm(self.policy.send_window_start)
        end_h, end_m = _parse_hhmm(self.policy.send_window_end)
        start = t.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
        end = t.replace(hour=end_h, minute=end_m, second=0, microsecond=0)
        return start <= t <= end

    # --- the decision -------------------------------------------------------
    def can_send_now(self, conn: sqlite3.Connection,
                     now: datetime | None = None) -> bool:
        return self.in_send_window(now) and self.remaining_today(conn, now) > 0

    def record_sent(self, conn: sqlite3.Connection, n: int = 1,
                    now: datetime | None = None) -> None:
        db.increment_sent(conn, self.today_str(now), n)
