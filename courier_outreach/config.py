"""Configuration: load everything from environment (.env in dev, real env vars
on the VPS) into one typed object. Fail loudly and early if something required
is missing when a module actually needs it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()  # no-op if there's no .env (e.g. on the VPS with real env vars)
except ImportError:
    # python-dotenv is a dev convenience. In production the process env is
    # already populated, so its absence is fine — just skip loading a file.
    pass


def _get(key: str, default: str | None = None) -> str | None:
    val = os.environ.get(key, default)
    return val.strip() if isinstance(val, str) else val


def _require(key: str) -> str:
    val = _get(key)
    if not val:
        raise RuntimeError(
            f"Missing required config: {key}. Set it in your .env "
            f"(see .env.example) or the VPS environment."
        )
    return val


def _int(key: str, default: int) -> int:
    raw = _get(key)
    return int(raw) if raw else default


def _bool(key: str, default: bool = False) -> bool:
    raw = _get(key)
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def _csv(key: str, default: str = "") -> list[str]:
    raw = _get(key, default) or ""
    return [p.strip() for p in raw.split(",") if p.strip()]


@dataclass(frozen=True)
class SmtpConfig:
    host: str
    port: int
    username: str
    password: str
    use_tls: bool
    from_name: str
    from_address: str
    reply_to: str

    @classmethod
    def load(cls) -> "SmtpConfig":
        return cls(
            host=_require("SMTP_HOST"),
            port=_int("SMTP_PORT", 587),
            username=_require("SMTP_USERNAME"),
            password=_require("SMTP_PASSWORD"),
            use_tls=_bool("SMTP_USE_TLS", True),
            from_name=_get("MAIL_FROM_NAME", "") or "",
            from_address=_require("MAIL_FROM_ADDRESS"),
            reply_to=_get("MAIL_REPLY_TO", _get("MAIL_FROM_ADDRESS")) or "",
        )


@dataclass(frozen=True)
class ImapConfig:
    host: str
    port: int
    username: str
    password: str
    mailbox: str

    @classmethod
    def load(cls) -> "ImapConfig":
        return cls(
            host=_require("IMAP_HOST"),
            port=_int("IMAP_PORT", 993),
            username=_require("IMAP_USERNAME"),
            password=_require("IMAP_PASSWORD"),
            mailbox=_get("IMAP_MAILBOX", "INBOX") or "INBOX",
        )


@dataclass(frozen=True)
class SendingPolicy:
    """The deliverability warm-up ramp + send window. See README > Deliverability."""

    warmup_start_per_day: int
    warmup_daily_increment: int
    warmup_max_per_day: int
    send_window_start: str   # "HH:MM" local
    send_window_end: str
    followup_days: list[int]

    def cap_for_day(self, day_index: int) -> int:
        """day_index is 0 on the first day the pipeline ever ran."""
        ramped = self.warmup_start_per_day + self.warmup_daily_increment * day_index
        return max(0, min(ramped, self.warmup_max_per_day))

    @classmethod
    def load(cls) -> "SendingPolicy":
        return cls(
            warmup_start_per_day=_int("WARMUP_START_PER_DAY", 10),
            warmup_daily_increment=_int("WARMUP_DAILY_INCREMENT", 5),
            warmup_max_per_day=_int("WARMUP_MAX_PER_DAY", 40),
            send_window_start=_get("SEND_WINDOW_START", "10:00") or "10:00",
            send_window_end=_get("SEND_WINDOW_END", "17:00") or "17:00",
            followup_days=[int(d) for d in _csv("FOLLOWUP_DAYS", "3,7")],
        )


@dataclass(frozen=True)
class BusinessProfile:
    name: str
    services: str
    coverage: str
    edge: str            # the one-line differentiator used in outreach copy
    website: str
    phone: str
    signature_name: str
    signature_title: str

    @classmethod
    def load(cls) -> "BusinessProfile":
        return cls(
            name=_get("BUSINESS_NAME", "Deep Cargo Movers") or "Deep Cargo Movers",
            services=_get("BUSINESS_SERVICES", "courier and cargo")
            or "courier and cargo",
            coverage=_get("BUSINESS_COVERAGE", "pan-India and worldwide")
            or "pan-India and worldwide",
            edge=_get("BUSINESS_EDGE",
                      "we handle every consignment with the same care as our own")
            or "we handle every consignment with the same care as our own",
            website=_get("BUSINESS_WEBSITE", "") or "",
            phone=_get("BUSINESS_PHONE", "") or "",
            signature_name=_get("SIGNATURE_NAME", "") or "",
            signature_title=_get("SIGNATURE_TITLE", "") or "",
        )


@dataclass(frozen=True)
class BookingRules:
    timezone: str
    meeting_days: list[str]
    hours_start: str
    hours_end: str
    default_duration_min: int
    min_notice_hours: int

    @classmethod
    def load(cls) -> "BookingRules":
        return cls(
            timezone=_get("TIMEZONE", "Asia/Kolkata") or "Asia/Kolkata",
            meeting_days=_csv("MEETING_DAYS", "Mon,Tue,Wed,Thu,Fri"),
            hours_start=_get("MEETING_HOURS_START", "10:00") or "10:00",
            hours_end=_get("MEETING_HOURS_END", "18:00") or "18:00",
            default_duration_min=_int("MEETING_DEFAULT_DURATION_MIN", 30),
            min_notice_hours=_int("MEETING_MIN_NOTICE_HOURS", 24),
        )


@dataclass(frozen=True)
class Config:
    run_mode: str            # "full_auto" | "supervised"
    database_path: Path
    log_level: str

    anthropic_api_key: str
    anthropic_model: str

    google_service_account_json: str
    google_sheet_id: str
    google_calendar_id: str

    app_host: str
    app_port: int
    app_access_token: str

    business: BusinessProfile
    booking: BookingRules
    policy: SendingPolicy

    @classmethod
    def load(cls) -> "Config":
        return cls(
            run_mode=(_get("RUN_MODE", "full_auto") or "full_auto").lower(),
            database_path=Path(_get("DATABASE_PATH", "./data/courier_outreach.sqlite3")),
            log_level=_get("LOG_LEVEL", "INFO") or "INFO",
            anthropic_api_key=_get("ANTHROPIC_API_KEY", "") or "",
            anthropic_model=_get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
            or "claude-haiku-4-5-20251001",
            google_service_account_json=_get("GOOGLE_SERVICE_ACCOUNT_JSON", "") or "",
            google_sheet_id=_get("GOOGLE_SHEET_ID", "") or "",
            google_calendar_id=_get("GOOGLE_CALENDAR_ID", "primary") or "primary",
            app_host=_get("APP_HOST", "0.0.0.0") or "0.0.0.0",
            app_port=_int("APP_PORT", 8080),
            app_access_token=_get("APP_ACCESS_TOKEN", "") or "",
            business=BusinessProfile.load(),
            booking=BookingRules.load(),
            policy=SendingPolicy.load(),
        )

    @property
    def is_full_auto(self) -> bool:
        return self.run_mode == "full_auto"
