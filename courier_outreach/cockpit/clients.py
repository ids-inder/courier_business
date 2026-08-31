"""Build authenticated Google API service objects from the service account.

Imports of the Google client libraries are lazy (inside the functions) so the
rest of the package — and its tests — don't require them to be installed.
"""

from __future__ import annotations

from ..config import Config

SCOPES_SHEETS = ["https://www.googleapis.com/auth/spreadsheets"]
SCOPES_CALENDAR = ["https://www.googleapis.com/auth/calendar.events"]


def _credentials(config: Config, scopes: list[str]):
    from google.oauth2 import service_account

    if not config.google_service_account_json:
        raise RuntimeError(
            "GOOGLE_SERVICE_ACCOUNT_JSON is not set — point it at your service "
            "account key file (see README > Setup)."
        )
    return service_account.Credentials.from_service_account_file(
        config.google_service_account_json, scopes=scopes
    )


def build_sheets_service(config: Config):
    from googleapiclient.discovery import build

    return build("sheets", "v4", credentials=_credentials(config, SCOPES_SHEETS),
                 cache_discovery=False)


def build_calendar_service(config: Config):
    from googleapiclient.discovery import build

    return build("calendar", "v3",
                 credentials=_credentials(config, SCOPES_CALENDAR),
                 cache_discovery=False)
