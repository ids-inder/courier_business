"""Rule-based reply triage (no AI).

Every reply is surfaced to you in the app to decide — this module only
pre-tags each one to save you time, and auto-catches unsubscribe requests so we
never email someone who asked us to stop.
"""

from .classifier import classify_reply, suggested_status  # noqa: F401
