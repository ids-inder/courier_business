"""Propose in-person meeting slots from the booking rules.

Pure and deterministic (pass in `now`) so it's easy to test. Generates the next
few openings on allowed weekdays, within meeting hours, respecting the minimum
notice period and meeting duration.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta

from ..config import BookingRules

_WEEKDAY_INDEX = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4,
                  "sat": 5, "sun": 6}


def _parse_hhmm(value: str) -> time:
    h, m = value.split(":", 1)
    return time(int(h), int(m))


def propose_slots(booking: BookingRules, now: datetime, count: int = 6,
                  horizon_days: int = 21) -> list[datetime]:
    allowed = {_WEEKDAY_INDEX[d.strip().lower()[:3]]
               for d in booking.meeting_days
               if d.strip().lower()[:3] in _WEEKDAY_INDEX}
    duration = timedelta(minutes=booking.default_duration_min)
    start_t = _parse_hhmm(booking.hours_start)
    end_t = _parse_hhmm(booking.hours_end)
    earliest = (now + timedelta(hours=booking.min_notice_hours)).replace(
        second=0, microsecond=0)

    slots: list[datetime] = []
    for day_offset in range(horizon_days):
        day = (earliest + timedelta(days=day_offset)).date()
        if day.weekday() not in allowed:
            continue
        slot = datetime.combine(day, start_t)
        day_end = datetime.combine(day, end_t)
        while slot + duration <= day_end:
            if slot >= earliest:
                slots.append(slot)
                if len(slots) >= count:
                    return slots
            slot += duration
    return slots
