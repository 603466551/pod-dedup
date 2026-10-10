"""Process logging that is safe to retain locally.

The operational log contains lifecycle and task identifiers only.  Detailed
image evidence stays in the existing database audit records, avoiding copied
user paths or filenames in a general-purpose log file.
"""

import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from app.core.config import settings

LOG_NAME = "pod_dedup"


def runtime_log_path() -> Path:
    return settings.data_dir / "logs" / "runtime.log"


def configure_runtime_logging() -> logging.Logger:
    logger = logging.getLogger(LOG_NAME)
    if any(getattr(handler, "name", "") == "pod-runtime-file" for handler in logger.handlers):
        return logger
    path = runtime_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = TimedRotatingFileHandler(
        path, when="midnight", backupCount=14, encoding="utf-8"
    )
    handler.name = "pod-runtime-file"
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


def read_recent_runtime_logs(limit: int) -> list[str]:
    """Read a bounded tail without exposing the host path through the API."""
    path = runtime_log_path()
    if not path.is_file():
        return []
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
    except OSError:
        return []
