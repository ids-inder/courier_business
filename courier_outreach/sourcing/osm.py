"""OpenStreetMap lead discovery via the Overpass API.

Free, no API key, no billing. We query for the kinds of places that ship
physical goods (factories, industrial units, wholesalers, company offices)
inside bounding boxes for Tricity and Baddi/BBN, and read whatever contact tags
OSM has (name, website, phone, sometimes email).

Coverage in Indian industrial areas is decent but uneven — treat this as one
feed among several (see CsvImportSource for a seed list). The query and boxes
below are tunable constants.
"""

from __future__ import annotations

import time
from typing import Iterable

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore

from .base import LeadCandidate

# Bounding boxes as (south, west, north, east) in degrees. Approximate — widen
# or split these as you learn the areas.
AREAS: dict[str, tuple[float, float, float, float]] = {
    # Chandigarh + Mohali + Panchkula
    "Tricity": (30.60, 76.60, 30.82, 76.90),
    # Baddi + Barotiwala + Nalagarh (BBN industrial belt, HP)
    "Baddi": (30.85, 76.65, 31.10, 76.95),
    # Haridwar + SIDCUL/BHEL industrial area (Uttarakhand)
    "Haridwar": (29.85, 77.95, 30.05, 78.25),
}

# Public Overpass endpoints; we try them in order on failure.
OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

# The OSM tag selectors that tend to mark goods-dispatching businesses.
_SELECTORS = [
    '["office"="company"]',
    '["man_made"="works"]',
    '["industrial"]',
    '["craft"]',
    '["building"="warehouse"]["name"]',
    '["building"="industrial"]["name"]',
    '["landuse"="industrial"]["name"]',
    '["shop"="trade"]',
    '["wholesale"]',
]


def build_query(bbox: tuple[float, float, float, float], timeout: int = 60) -> str:
    """Build an Overpass QL query returning tagged nodes/ways/relations in bbox."""
    s, w, n, e = bbox
    box = f"({s},{w},{n},{e})"
    parts = "\n  ".join(f"nwr{sel}{box};" for sel in _SELECTORS)
    return f"[out:json][timeout:{timeout}];\n(\n  {parts}\n);\nout center tags;"


def _industry_from_tags(tags: dict) -> str | None:
    for key in ("industrial", "product", "craft", "office", "man_made",
                "shop", "wholesale"):
        val = tags.get(key)
        if val and val not in {"yes", "company"}:
            return str(val).replace("_", " ")
    if tags.get("office") == "company":
        return "company"
    if tags.get("man_made") == "works":
        return "manufacturing"
    return None


def parse_overpass(payload: dict, area: str) -> list[LeadCandidate]:
    """Turn an Overpass JSON response into candidates. Only elements with a
    name are kept — an unnamed factory polygon isn't a lead.
    """
    out: list[LeadCandidate] = []
    for el in payload.get("elements", []):
        tags = el.get("tags") or {}
        name = tags.get("name") or tags.get("operator")
        if not name:
            continue
        website = (tags.get("website") or tags.get("contact:website")
                   or tags.get("url"))
        email = (tags.get("email") or tags.get("contact:email"))
        phone = (tags.get("phone") or tags.get("contact:phone")
                 or tags.get("contact:mobile"))
        out.append(LeadCandidate(
            company=name.strip(),
            area=area,
            industry=_industry_from_tags(tags),
            website=website,
            contact_email=email,
            phone=phone,
            source="openstreetmap",
        ).normalized())
    return out


class OverpassSource:
    """Discovers leads from OpenStreetMap. Implements the Source protocol."""

    name = "openstreetmap"

    def __init__(self, areas: dict | None = None, polite_delay: float = 2.0):
        self.areas = areas or AREAS
        self.polite_delay = polite_delay

    def _fetch(self, query: str) -> dict:
        if httpx is None:
            raise RuntimeError("httpx is required for live OSM discovery")
        last_err: Exception | None = None
        for endpoint in OVERPASS_ENDPOINTS:
            try:
                resp = httpx.post(endpoint, data={"data": query}, timeout=90.0)
                resp.raise_for_status()
                return resp.json()
            except Exception as err:  # try the next mirror
                last_err = err
                time.sleep(self.polite_delay)
        raise RuntimeError(f"All Overpass endpoints failed: {last_err}")

    def discover(self) -> Iterable[LeadCandidate]:
        for area, bbox in self.areas.items():
            payload = self._fetch(build_query(bbox))
            yield from parse_overpass(payload, area)
            time.sleep(self.polite_delay)  # be a good Overpass citizen
