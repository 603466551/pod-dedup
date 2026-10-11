from types import SimpleNamespace

from app.api.tasks import archive_progress


def test_archive_progress_counts_pending_completed_and_failed_archive_items() -> None:
    items = [
        SimpleNamespace(status="READY_TO_ARCHIVE", error_code=None),
        SimpleNamespace(status="ARCHIVED", error_code=None),
        SimpleNamespace(status="ERROR", error_code="ARCHIVE_FAILED"),
        SimpleNamespace(status="AUTO_DELETED", error_code=None),
    ]

    assert archive_progress(items) == {"completed": 1, "total": 3, "failed": 1}


def test_archive_progress_omits_tasks_without_archive_items() -> None:
    assert archive_progress([SimpleNamespace(status="AUTO_DELETED", error_code=None)]) is None
