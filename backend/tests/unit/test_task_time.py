from datetime import datetime

from app.services.task_time import worker_timestamp_for_display


def test_worker_utc_timestamp_is_serialized_in_task_timezone() -> None:
    value = datetime(2026, 10, 9, 1, 46, 48)

    assert worker_timestamp_for_display(value, {"app_timezone": "Asia/Shanghai"}) == "2026-10-09T09:46:48+08:00"
