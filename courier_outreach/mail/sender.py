"""Send a single email over Gmail SMTP.

Kept deliberately small: build a well-formed MIME message (with the headers that
help deliverability and compliance) and put it on the wire. *Who* to email and
*what* to say lives in the orchestrator + templates; *how many* is the
governor's job. This module just sends one message correctly.
"""

from __future__ import annotations

import smtplib
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

from ..config import SmtpConfig


def _sender_domain(from_address: str) -> str:
    return from_address.split("@", 1)[1] if "@" in from_address else "localhost"


def build_message(cfg: SmtpConfig, to_addr: str, subject: str, body_text: str,
                  body_html: str | None = None,
                  add_unsubscribe: bool = True) -> EmailMessage:
    """Construct the MIME message with sensible, deliverability-friendly headers.

    We add a `List-Unsubscribe` header pointing at a mailto on our own address —
    honouring opt-outs is both good practice and a spam-filter positive. The
    reply reader treats such messages as unsubscribe requests.
    """
    msg = EmailMessage()
    msg["From"] = formataddr((cfg.from_name or None, cfg.from_address))
    msg["To"] = to_addr
    if cfg.reply_to:
        msg["Reply-To"] = cfg.reply_to
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=_sender_domain(cfg.from_address))

    if add_unsubscribe:
        unsub = f"<mailto:{cfg.from_address}?subject=unsubscribe>"
        msg["List-Unsubscribe"] = unsub
        msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"

    msg.set_content(body_text)
    if body_html:
        msg.add_alternative(body_html, subtype="html")
    return msg


def send_message(cfg: SmtpConfig, msg: EmailMessage) -> str:
    """Put a prepared message on the wire. Returns its Message-ID."""
    with smtplib.SMTP(cfg.host, cfg.port, timeout=30) as server:
        server.ehlo()
        if cfg.use_tls:
            server.starttls()
            server.ehlo()
        server.login(cfg.username, cfg.password)
        server.send_message(msg)
    return msg["Message-ID"]


def send_email(cfg: SmtpConfig, to_addr: str, subject: str, body_text: str,
               body_html: str | None = None,
               add_unsubscribe: bool = True) -> str:
    """Convenience: build and send in one call. Returns the Message-ID."""
    msg = build_message(cfg, to_addr, subject, body_text, body_html,
                        add_unsubscribe)
    return send_message(cfg, msg)
