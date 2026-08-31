"""Read the contact email a company publishes on its OWN website.

This is the defensible, high-yield way to get emails: a business putting its
address on its own site is publishing it to be contacted. We never guess or
construct addresses (guessed addresses tank deliverability) — we only use what's
actually printed on the page.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

try:
    import httpx
except ImportError:  # httpx is required at runtime; keep import-time soft for tests
    httpx = None  # type: ignore

from bs4 import BeautifulSoup

# A pragmatic email regex — good enough for scraping printed addresses.
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

# Common de-obfuscations: "info [at] acme [dot] com" -> "info@acme.com".
_DEOBFUSCATE = [
    (re.compile(r"\s*\[?\(?\s*at\s*\)?\]?\s*", re.I), "@"),
    (re.compile(r"\s*\[?\(?\s*dot\s*\)?\]?\s*", re.I), "."),
]

# Reject these — they're placeholders, asset filenames, or vendor noise, never
# a real business contact.
_JUNK_SUBSTRINGS = {
    "example.com", "example.org", "yourdomain", "your-email", "youremail",
    "domain.com", "email@", "sentry.io", "wixpress.com", "godaddy.com",
    "wordpress", "no-reply", "noreply", "donotreply", "u003e", "@2x",
    "core.min", "react", "schema.org", ".png", ".jpg", ".jpeg", ".gif",
    ".webp", ".svg", ".css", ".js",
}

# Prefer these local-parts — they're the general business inbox, most likely
# to be read and answered.
_ROLE_PRIORITY = [
    "sales", "enquiry", "enquiries", "inquiry", "info", "contact", "hello",
    "business", "bd", "marketing", "office", "care", "support", "admin",
]

# Pages likely to carry a contact address, tried after the homepage.
_CONTACT_PATHS = [
    "contact", "contact-us", "contactus", "contact_us", "about", "about-us",
    "reach-us", "get-in-touch", "connect", "enquiry",
]

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; CourierOutreachBot/0.1; +contact via email)"
    )
}


def _is_junk(email: str) -> bool:
    e = email.lower()
    if any(j in e for j in _JUNK_SUBSTRINGS):
        return True
    # local-part all digits/hex (usually a tracking pixel or hash), or absurd length
    local = e.split("@", 1)[0]
    if len(e) > 100 or len(local) > 64:
        return True
    return False


def extract_emails_from_html(html: str, site_domain: str | None = None) -> list[str]:
    """Pull candidate emails from a page, best first.

    Ranking: same-domain addresses beat off-domain ones; role inboxes
    (sales@/info@/…) beat personal ones. `site_domain` is the registrable host
    of the site we're on, used for the same-domain bonus.
    """
    found: set[str] = set()

    # 1) mailto: links are the strongest signal.
    soup = BeautifulSoup(html, "lxml")
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.lower().startswith("mailto:"):
            addr = href[7:].split("?", 1)[0].strip()
            if addr:
                found.add(addr)

    # 2) De-obfuscate then regex-scan the visible text + raw html.
    text = soup.get_text(" ", strip=True)
    for blob in (text, html):
        deob = blob
        for pat, repl in _DEOBFUSCATE:
            deob = pat.sub(repl, deob)
        for m in EMAIL_RE.findall(deob):
            found.add(m)

    candidates = [e.strip().lower().rstrip(".") for e in found]
    candidates = [e for e in candidates if not _is_junk(e)]
    candidates = list(dict.fromkeys(candidates))  # de-dupe, keep order

    def score(email: str) -> tuple:
        local, _, domain = email.partition("@")
        same_domain = bool(site_domain) and site_domain.lower() in domain
        try:
            role_rank = _ROLE_PRIORITY.index(local)
        except ValueError:
            role_rank = len(_ROLE_PRIORITY)
        # sort key: same-domain first (0), then role priority, then shortest
        return (0 if same_domain else 1, role_rank, len(email))

    return sorted(candidates, key=score)


def _registrable_host(url: str) -> str | None:
    try:
        host = urlparse(url).netloc.lower()
    except ValueError:
        return None
    if host.startswith("www."):
        host = host[4:]
    return host or None


def find_company_emails(website: str, client: "httpx.Client | None" = None,
                        max_pages: int = 5) -> list[str]:
    """Fetch the homepage and a few likely contact pages, return ranked emails.

    Network failures are swallowed (return what we have) — a site being down is
    normal and shouldn't crash a sourcing run.
    """
    if httpx is None:
        raise RuntimeError("httpx is required for live email extraction")

    if not website.startswith(("http://", "https://")):
        website = "https://" + website

    site_domain = _registrable_host(website)
    owns_client = client is None
    client = client or httpx.Client(
        headers=_HEADERS, follow_redirects=True, timeout=15.0
    )

    urls = [website] + [urljoin(website + "/", p) for p in _CONTACT_PATHS]
    seen_urls: set[str] = set()
    collected: list[str] = []
    try:
        for url in urls[:max_pages]:
            if url in seen_urls:
                continue
            seen_urls.add(url)
            try:
                resp = client.get(url)
                if resp.status_code != 200 or "text/html" not in \
                        resp.headers.get("content-type", "text/html"):
                    continue
                for email in extract_emails_from_html(resp.text, site_domain):
                    if email not in collected:
                        collected.append(email)
            except Exception:
                continue
            if collected and url == website:
                # Homepage already yielded something good; still peek at one
                # contact page for a better role address, then stop early.
                continue
    finally:
        if owns_client:
            client.close()

    # Re-rank the union so the overall best address wins.
    if collected:
        html_join = " ".join(collected)  # cheap: re-score by the same key
        return extract_emails_from_html(
            " ".join(f'<a href="mailto:{e}">{e}</a>' for e in collected),
            site_domain,
        )
    return []


def best_email(website: str, client: "httpx.Client | None" = None) -> str | None:
    emails = find_company_emails(website, client=client)
    return emails[0] if emails else None
