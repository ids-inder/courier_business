"""Render a preset template for a specific lead.

Fills `{merge_field}` placeholders from the lead row + BusinessProfile. Missing
fields render as empty rather than raising, so a lead with no `industry` (say)
still produces a clean email.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from ..config import BusinessProfile
from ..models import LeadStatus

TEMPLATE_DIR = Path(__file__).parent

# The follow-up ladder, in order.
SEQUENCE = ["first_touch", "followup_1", "followup_2"]


class _SafeDict(dict):
    def __missing__(self, key):  # leave unknown placeholders blank
        return ""


@dataclass
class RenderedEmail:
    subject: str
    body_text: str


def load_template(name: str) -> tuple[str, str]:
    """Return (subject_template, body_template) for a template name."""
    if name not in SEQUENCE:
        raise ValueError(f"unknown template: {name!r} (have {SEQUENCE})")
    lines = (TEMPLATE_DIR / f"{name}.txt").read_text(encoding="utf-8").splitlines()
    subject = ""
    body_start = 0
    for i, line in enumerate(lines):
        if line.strip().lower().startswith("subject:"):
            subject = line.split(":", 1)[1].strip()
            body_start = i + 1
            break
    body = "\n".join(lines[body_start:]).strip("\n")
    return subject, body


def build_context(lead: Mapping, business: BusinessProfile) -> dict:
    area = (lead["area"] if lead["area"] else None) or "your area"
    return {
        "company": lead["company"],
        "area": area,
        "industry": lead["industry"] or "",
        "contact_name": lead["contact_name"] or "",
        "business_name": business.name,
        "services": business.services,
        "coverage": business.coverage,
        "edge": business.edge,
        "signature_name": business.signature_name,
        "phone": business.phone,
    }


def render(name: str, lead: Mapping, business: BusinessProfile) -> RenderedEmail:
    subject_tmpl, body_tmpl = load_template(name)
    ctx = _SafeDict(build_context(lead, business))
    return RenderedEmail(
        subject=subject_tmpl.format_map(ctx).strip(),
        body_text=body_tmpl.format_map(ctx).strip() + "\n",
    )


def template_for_status(status: LeadStatus) -> str | None:
    """Which template to send next, given where the lead is in the ladder."""
    return {
        LeadStatus.NEW: "first_touch",
        LeadStatus.QUEUED: "first_touch",
        LeadStatus.SENT: "followup_1",
        LeadStatus.FOLLOWUP_1: "followup_2",
    }.get(status)
