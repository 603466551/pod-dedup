"""Small local runtime state used by the health endpoint.

This file deliberately stores only process liveness metadata.  Task records in
MySQL remain the audit source for image work, so no user paths or filenames are
written here.
"""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import settings


def worker_heartbeat_path() -> Path:
    return settings.data_dir / "runtime" / "worker-heartbeat.json"


def write_worker_heartbeat() -> None:
    path = worker_heartbeat_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"pid": os.getpid(), "seen_at": datetime.now(UTC).isoformat()}),
        encoding="utf-8",
    )


def worker_health(max_age_seconds: int = 10) -> dict[str, str | None]:
    path = worker_heartbeat_path()
    if not path.is_file():
        return {"status": "NOT_STARTED", "last_seen": None}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        seen_at = datetime.fromisoformat(data["seen_at"])
        age = (datetime.now(UTC) - seen_at).total_seconds()
        return {
            "status": "READY" if age <= max_age_seconds else "STALE",
            "last_seen": seen_at.isoformat(),
        }
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return {"status": "STALE", "last_seen": None}
