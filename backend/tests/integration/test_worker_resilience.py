import os
import uuid

import pytest
from sqlalchemy import delete


@pytest.mark.skipif(not os.getenv("MYSQL_TEST_DATABASE_URL"), reason="需要隔离的MySQL测试库")
def test_unhandled_task_error_marks_only_that_task_failed(monkeypatch) -> None:
    os.environ["DATABASE_URL"] = os.environ["MYSQL_TEST_DATABASE_URL"]

    from app.core.db import SessionLocal
    from app.models.images import DuplicatePair, FileOperation, Image, ImageFeature, ImageFile, Review, TaskItem, VlmCall
    from app.models.tasks import Task, TaskEvent, TaskResourceLock
    from app.workers import runner

    with SessionLocal() as session:
        for model in (VlmCall, TaskResourceLock, Review, DuplicatePair, FileOperation, ImageFeature, ImageFile, TaskItem, Image, TaskEvent, Task):
            session.execute(delete(model))
        task = Task(type="SOURCE_ORGANIZE", status="CREATED", idempotency_key=str(uuid.uuid4()), settings_snapshot={}, counters={}, warnings=[])
        session.add(task)
        session.commit()
        task_id = task.id

    def raise_unexpected(*_args, **_kwargs) -> None:
        raise RuntimeError("unexpected test failure")

    monkeypatch.setattr(runner, "run_m1_scan", raise_unexpected)
    assert runner.run_one_task() is True

    with SessionLocal() as session:
        task = session.get(Task, task_id)
        events = list(session.query(TaskEvent).filter(TaskEvent.task_id == task_id))
        assert task is not None and task.status == "FAILED"
        assert task.lease_until is None and task.finished_at is not None
        assert any(event.level == "ERROR" for event in events)
