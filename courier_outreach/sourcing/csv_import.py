"""Import leads from a CSV you provide — a hand-built seed list, or an official
export from an IndiaMART/JustDial seller account.

Columns are matched case-insensitively and flexibly, so a file with headers like
"Company Name, Email, Website, Phone, City" just works. Only a company name is
required per row.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable

from .base import LeadCandidate

# Map many possible header spellings to our canonical fields.
_ALIASES: dict[str, tuple[str, ...]] = {
    "company": ("company", "company name", "name", "business", "firm", "organisation",
                "organization"),
    "contact_email": ("email", "e-mail", "email address", "mail"),
    "website": ("website", "site", "url", "web"),
    "phone": ("phone", "mobile", "contact", "phone number", "tel"),
    "contact_name": ("contact name", "person", "owner", "contact person"),
    "area": ("area", "city", "location", "region"),
    "industry": ("industry", "sector", "category", "segment"),
}


def _build_header_map(fieldnames: list[str]) -> dict[str, str]:
    """Return {canonical_field: actual_header} for the columns we recognise."""
    lookup = {h.strip().lower(): h for h in fieldnames if h}
    mapping: dict[str, str] = {}
    for canonical, aliases in _ALIASES.items():
        for alias in aliases:
            if alias in lookup:
                mapping[canonical] = lookup[alias]
                break
    return mapping


class CsvImportSource:
    """Reads candidates from a CSV file. Implements the Source protocol."""

    name = "csv_import"

    def __init__(self, path: str | Path, default_area: str | None = None):
        self.path = Path(path)
        self.default_area = default_area

    def discover(self) -> Iterable[LeadCandidate]:
        with self.path.open(newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            if not reader.fieldnames:
                return
            hmap = _build_header_map(list(reader.fieldnames))
            if "company" not in hmap:
                raise ValueError(
                    f"{self.path}: could not find a company/name column. "
                    f"Headers seen: {reader.fieldnames}"
                )
            for row in reader:
                company = (row.get(hmap["company"]) or "").strip()
                if not company:
                    continue
                yield LeadCandidate(
                    company=company,
                    area=(row.get(hmap["area"]).strip() if "area" in hmap
                          and row.get(hmap["area"]) else self.default_area),
                    industry=(row.get(hmap["industry"]) if "industry" in hmap else None),
                    website=(row.get(hmap["website"]) if "website" in hmap else None),
                    contact_email=(row.get(hmap["contact_email"])
                                   if "contact_email" in hmap else None),
                    contact_name=(row.get(hmap["contact_name"])
                                  if "contact_name" in hmap else None),
                    phone=(row.get(hmap["phone"]) if "phone" in hmap else None),
                    source="csv_import",
                ).normalized()
