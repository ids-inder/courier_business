"""Shared types for the sourcing layer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol


@dataclass
class LeadCandidate:
    """A company discovered by a source, before it's persisted as a lead.

    Only `company` is required. Everything else is best-effort; missing fields
    are filled in later (e.g. the email is often found by visiting `website`).
    """

    company: str
    area: str | None = None          # "Tricity" | "Baddi"
    industry: str | None = None
    website: str | None = None
    contact_email: str | None = None
    contact_name: str | None = None
    phone: str | None = None
    source: str = "unknown"
    notes: str | None = None

    def normalized(self) -> "LeadCandidate":
        """Tidy whitespace, lowercase the email, and coerce blank optional
        fields to None (so the DB stores NULL, not '', and de-duping is clean).
        """
        def clean(v: str | None) -> str | None:
            return v.strip() if isinstance(v, str) and v.strip() else None

        self.company = (self.company or "").strip()
        self.area = clean(self.area)
        self.industry = clean(self.industry)
        self.website = clean(self.website)
        self.contact_name = clean(self.contact_name)
        self.phone = clean(self.phone)
        self.notes = clean(self.notes)
        email = clean(self.contact_email)
        self.contact_email = email.lower() if email else None
        return self


class Source(Protocol):
    """Anything that can yield candidate leads."""

    name: str

    def discover(self) -> Iterable[LeadCandidate]:
        ...
