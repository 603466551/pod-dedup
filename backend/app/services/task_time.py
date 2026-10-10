"""Serialize Worker UTC timestamps for the task's configured display timezone."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from app.core.config import settings


def worker_timestamp_for_display(value: datetime | None, task_settings: dict | None) -> str | None:
    if value is None:
        return None
    timezone_name = (task_settings or {}).get("app_timezone", settings.app_timezone)
    # Worker lease/start/end timestamps are stored as UTC-naive values so
    # MySQL 5.7 comparisons remain unambiguous.  Attach UTC only at the API
    # boundary, then return an offset-aware local value to the browser.
    return value.replace(tzinfo=UTC).astimezone(ZoneInfo(timezone_name)).isoformat()
