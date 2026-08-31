"""Keyword reply classifier.

Deliberately simple and transparent — you can read exactly why a reply was
tagged the way it was, and every reply is still shown to you in the app for the
final call. The one tag we act on automatically is UNSUBSCRIBE (we suppress the
lead immediately).

Order matters: unsubscribe and auto-replies are checked first, and NEGATIVE is
checked before POSITIVE so "not interested" isn't mistaken for interest.
"""

from __future__ import annotations

import re

from ..models import LeadStatus, ReplyClass

_UNSUBSCRIBE = [
    "unsubscribe", "remove me", "remove my", "stop emailing", "stop sending",
    "do not contact", "don't contact", "opt out", "opt-out", "take me off",
]
_AUTOREPLY = [
    "out of office", "out-of-office", "auto-reply", "auto reply",
    "automatic reply", "on leave", "on vacation", "away from my", "autoreply",
]
_NEGATIVE = [
    "not interested", "no thanks", "no thank you", "already have",
    "already using", "already associated", "not required", "no requirement",
    "no need", "we are covered", "not looking", "don't need", "do not need",
]
_POSITIVE = [
    "interested", "please call", "call me", "give me a call", "send rates",
    "send details", "send quote", "share rates", "share details", "share more",
    "how much", "your rates", "let's meet", "lets meet", "would like",
    "tell me more", "send more", "sounds good", "go ahead", "please share",
    "yes", "sure", "okay", "ok",
]


def _contains(text: str, phrases: list[str]) -> bool:
    """Whole-word/phrase match so 'yes' doesn't fire inside 'yesterday'."""
    for p in phrases:
        if re.search(r"\b" + re.escape(p) + r"\b", text):
            return True
    return False


def classify_reply(text: str) -> ReplyClass:
    t = (text or "").lower()
    if _contains(t, _UNSUBSCRIBE):
        return ReplyClass.UNSUBSCRIBE
    if _contains(t, _AUTOREPLY):
        return ReplyClass.AUTOREPLY
    if _contains(t, _NEGATIVE):
        return ReplyClass.NEGATIVE
    if _contains(t, _POSITIVE):
        return ReplyClass.POSITIVE
    if "?" in t:
        return ReplyClass.QUESTION
    return ReplyClass.UNKNOWN


def suggested_status(reply_class: ReplyClass) -> LeadStatus | None:
    """The lead status this reply implies. None = leave the status as-is
    (auto-replies don't change anything)."""
    return {
        ReplyClass.POSITIVE: LeadStatus.REPLIED_POSITIVE,
        ReplyClass.QUESTION: LeadStatus.REPLIED_QUESTION,
        ReplyClass.UNKNOWN: LeadStatus.REPLIED_QUESTION,   # surface for review
        ReplyClass.NEGATIVE: LeadStatus.REPLIED_NEGATIVE,
        ReplyClass.UNSUBSCRIBE: LeadStatus.UNSUBSCRIBED,
        ReplyClass.AUTOREPLY: None,
    }.get(reply_class)
