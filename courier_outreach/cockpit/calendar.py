"""Booking: create the Google Calendar event and email the lead a confirmation.

Called once YOU confirm a time in the app. We deliberately do NOT rely on
Calendar's own attendee-invite emails (finicky for a service account on a
consumer calendar) — we create the event on your calendar and send the lead a
plain confirmation through our own SMTP, which we fully control.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta

from ..config import Config, SmtpConfig
from ..mail import sender
from ..models import LeadStatus
from .. import db
from .clients import build_calendar_service

log = logging.getLogger(__name__)


def build_event_body(summary: str, description: str, start_dt: datetime,
                     end_dt: datetime, timezone: str) -> dict:
    return {
        "summary": summary,
        "description": description,
        "start": {"dateTime": start_dt.isoformat(), "timeZone": timezone},
        "end": {"dateTime": end_dt.isoformat(), "timeZone": timezone},
        "reminders": {"useDefault": True},
    }


def create_event(service, calendar_id: str, summary: str, description: str,
                 start_dt: datetime, end_dt: datetime, timezone: str) -> dict:
    body = build_event_body(summary, description, start_dt, end_dt, timezone)
    return service.events().insert(calendarId=calendar_id, body=body).execute()


def confirmation_email(business, lead_company: str, when_str: str) -> tuple[str, str]:
    subject = f"Meeting confirmed — {business.name}"
    body = (
        f"Hello,\n\n"
        f"Thank you — our meeting is confirmed for {when_str}.\n\n"
        f"I look forward to discussing how {business.name} can handle "
        f"{lead_company}'s courier and cargo dispatch.\n\n"
        f"Warm regards,\n"
        f"{business.signature_name}\n"
        f"{business.name} · {business.phone}\n"
    )
    return subject, body


def book_meeting(config: Config, conn: sqlite3.Connection, lead_id: int,
                 start_dt: datetime, *, smtp_config: SmtpConfig | None = None,
                 duration_min: int | None = None, calendar_service=None,
                 send_confirmation: bool = True) -> dict:
    """Create the calendar event, email the lead, mark the lead BOOKED.

    Returns the created event resource.
    """
    lead = db.get_lead(conn, lead_id)
    if lead is None:
        raise ValueError(f"no lead with id {lead_id}")

    duration = duration_min or config.booking.default_duration_min
    end_dt = start_dt + timedelta(minutes=duration)
    tz = config.booking.timezone

    summary = f"Meeting: {lead['company']} — {config.business.name}"
    description = (
        f"In-person meeting with {lead['company']}.\n"
        f"Contact: {lead['contact_name'] or ''} | "
        f"{lead['contact_email'] or ''} | {lead['phone'] or ''}"
    )

    service = calendar_service or build_calendar_service(config)
    event = create_event(service, config.google_calendar_id, summary,
                         description, start_dt, end_dt, tz)

    when_str = start_dt.strftime("%A, %d %b %Y at %I:%M %p")
    if send_confirmation and lead["contact_email"] and smtp_config is not None:
        subject, body = confirmation_email(config.business, lead["company"], when_str)
        try:
            sender.send_email(smtp_config, lead["contact_email"], subject, body,
                              add_unsubscribe=False)
        except Exception as err:  # booking still succeeds; log the email failure
            log.warning("confirmation email to %s failed: %s",
                        lead["contact_email"], err)

    db.set_status(conn, lead_id, LeadStatus.BOOKED,
                  meeting_time=start_dt.isoformat(),
                  notes=f"Meeting booked for {when_str}")
    db.audit(conn, lead_id, "meeting_booked", when_str)
    return event
