"""Domain model: the lead lifecycle, reply classes, and the Google Sheet
column schema. These are the shared vocabulary every module speaks.
"""

from __future__ import annotations

from enum import Enum


class LeadStatus(str, Enum):
    """The lifecycle of a single company from discovery to booked meeting.

    Flow (happy path):
        NEW -> QUEUED -> SENT -> (FOLLOWUP_1/2) -> REPLIED_POSITIVE
            -> MEETING_PROPOSED -> MEETING_CONFIRMED -> BOOKED

    Terminal off-ramps: REPLIED_NEGATIVE, UNSUBSCRIBED, BOUNCED, CLOSED.
    """

    NEW = "new"                      # discovered, no email yet
    QUEUED = "queued"                # ready/approved to send
    SENT = "sent"                    # first email sent
    FOLLOWUP_1 = "followup_1"        # first follow-up sent
    FOLLOWUP_2 = "followup_2"        # second follow-up sent
    REPLIED_POSITIVE = "replied_positive"   # interested -> needs booking
    REPLIED_QUESTION = "replied_question"   # asked something -> needs a reply
    REPLIED_NEGATIVE = "replied_negative"   # not interested -> stop
    UNSUBSCRIBED = "unsubscribed"    # opted out -> never contact again
    BOUNCED = "bounced"              # hard bounce -> drop
    MEETING_PROPOSED = "meeting_proposed"   # agent proposed slots to the user
    MEETING_CONFIRMED = "meeting_confirmed" # user picked a slot in the app
    BOOKED = "booked"                # calendar event created + invite sent
    CLOSED = "closed"                # done / dead

    @property
    def is_terminal(self) -> bool:
        return self in {
            LeadStatus.REPLIED_NEGATIVE,
            LeadStatus.UNSUBSCRIBED,
            LeadStatus.BOUNCED,
            LeadStatus.BOOKED,
            LeadStatus.CLOSED,
        }

    @property
    def is_contactable(self) -> bool:
        """May we still send this lead an (outreach) email?"""
        return self in {LeadStatus.NEW, LeadStatus.QUEUED, LeadStatus.SENT,
                        LeadStatus.FOLLOWUP_1}


class ReplyClass(str, Enum):
    """How Claude classifies an inbound reply."""

    POSITIVE = "positive"        # wants to talk / meet
    QUESTION = "question"        # needs info before deciding
    NEGATIVE = "negative"        # not interested
    UNSUBSCRIBE = "unsubscribe"  # asked to stop / remove
    AUTOREPLY = "autoreply"      # OOO / no-reply bounce-ish, ignore
    UNKNOWN = "unknown"


class MessageDirection(str, Enum):
    OUTBOUND = "outbound"
    INBOUND = "inbound"


# --- Google Sheet cockpit: column order, left to right ----------------------
# The Sheet is a human-readable projection of the leads table. This list is the
# single source of truth for the header row and the write order.
SHEET_COLUMNS: list[str] = [
    "Company",
    "Area",            # Tricity | Baddi
    "Industry",
    "Website",
    "Contact Email",
    "Contact Name",
    "Phone",
    "Status",
    "Last Email",
    "Next Action",
    "Reply Summary",
    "Meeting Time",
    "Source",
    "Notes",
]
