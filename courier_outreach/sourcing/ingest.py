"""Run a source, enrich each candidate with a published email, and persist.

This is the glue between the sourcing layer and the DB. It de-dupes (via
db.upsert_lead), so running the same source twice is safe and idempotent.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from typing import Callable

from .. import db
from .base import LeadCandidate, Source

log = logging.getLogger(__name__)

# Injectable so tests don't hit the network. Signature: (website) -> email|None.
EmailFinder = Callable[[str], "str | None"]


@dataclass
class IngestReport:
    seen: int = 0            # candidates yielded by the source
    inserted: int = 0        # brand-new leads created
    duplicates: int = 0      # already in the DB
    emails_found: int = 0    # emails discovered by visiting a website
    emailable: int = 0       # leads that ended up with an email address

    def __str__(self) -> str:
        return (f"seen={self.seen} inserted={self.inserted} "
                f"duplicates={self.duplicates} emails_found={self.emails_found} "
                f"emailable={self.emailable}")


def _default_email_finder(website: str) -> str | None:
    # Imported lazily so importing this module doesn't require httpx.
    from .website_email import best_email
    return best_email(website)


def ingest(conn: sqlite3.Connection, source: Source, *,
           enrich_emails: bool = True,
           email_finder: EmailFinder | None = None,
           limit: int | None = None) -> IngestReport:
    """Pull candidates from `source` and upsert them.

    If a candidate has no email but has a website and `enrich_emails` is on, we
    visit the site to find the email it publishes.
    """
    finder = email_finder or _default_email_finder
    report = IngestReport()

    for cand in source.discover():
        if limit is not None and report.seen >= limit:
            break
        report.seen += 1
        cand = cand.normalized()
        if not cand.company:
            continue

        if enrich_emails and not cand.contact_email and cand.website:
            try:
                email = finder(cand.website)
            except Exception as err:
                log.warning("email lookup failed for %s: %s", cand.website, err)
                email = None
            if email:
                cand.contact_email = email.strip().lower()
                report.emails_found += 1

        # Was this company already known? Check before upserting for an
        # accurate inserted/duplicate split.
        already = db.find_existing(conn, cand.company, cand.area, cand.contact_email)
        lead_id = db.upsert_lead(
            conn,
            company=cand.company,
            area=cand.area,
            industry=cand.industry,
            website=cand.website,
            contact_email=cand.contact_email,
            contact_name=cand.contact_name,
            phone=cand.phone,
            source=cand.source or source.name,
            notes=cand.notes,
        )
        if already is None:
            report.inserted += 1
        else:
            report.duplicates += 1

        row = db.get_lead(conn, lead_id)
        if row and row["contact_email"]:
            report.emailable += 1

    db.audit(conn, None, "ingest_run", f"{source.name}: {report}")
    log.info("ingest(%s): %s", source.name, report)
    return report
