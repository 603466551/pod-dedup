"""Worker persistence test against the isolated MySQL test database."""

import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image as PillowImage
from sqlalchemy import delete, update


@pytest.mark.skipif(not os.getenv("MYSQL_TEST_DATABASE_URL"), reason="需要隔离的MySQL测试库")
def test_worker_scans_task_after_api_client_closes(tmp_path: Path) -> None:
    database_url = os.environ["MYSQL_TEST_DATABASE_URL"]
    assert "pod_dedup_test" in database_url
    os.environ["DATABASE_URL"] = database_url

    from app.core.db import SessionLocal
    from app.models.images import DuplicatePair, FileOperation, Image, ImageFeature, ImageFile, Review, TaskItem
    from app.models.tasks import Task, TaskEvent, TaskResourceLock
    from app.main import app
    from app.workers.runner import claim_one_task, run_m1_scan

    with SessionLocal() as session:
        for model in (TaskResourceLock, Review, DuplicatePair, FileOperation, ImageFeature, ImageFile, TaskItem, Image, TaskEvent, Task):
            session.execute(delete(model))
        session.commit()

    batch = tmp_path / "source-batch"
    library = tmp_path / "source-library"
    pod_library = tmp_path / "pod-library"
    for directory in (batch, library, pod_library):
        directory.mkdir()
    PillowImage.new("RGB", (8, 8), "blue").save(batch / "one.png")

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/tasks/source-dedup",
            json={
                "source_batch_dir": str(batch),
                "source_library_dir": str(library),
                "pod_library_dir": str(pod_library),
                "dry_run": True,
                "idempotency_key": str(uuid.uuid4()),
            },
        )
    task_id = int(response.json()["task_id"])

    with SessionLocal() as worker_session:
        task = claim_one_task(worker_session)
        assert task is not None and task.id == task_id
        run_m1_scan(task, worker_session)

    with SessionLocal() as verification_session:
        persisted = verification_session.get(Task, task_id)
        assert persisted is not None
        assert persisted.status == "DONE"
        assert persisted.counters["processed"] == 1


@pytest.mark.skipif(not os.getenv("MYSQL_TEST_DATABASE_URL"), reason="需要隔离的MySQL测试库")
def test_worker_reclaims_expired_nonterminal_task() -> None:
    os.environ["DATABASE_URL"] = os.environ["MYSQL_TEST_DATABASE_URL"]
    from app.core.db import SessionLocal
    from app.models.tasks import Task, TaskResourceLock
    from app.workers.runner import claim_one_task

    with SessionLocal() as session:
        session.execute(delete(TaskResourceLock))
        session.execute(update(Task).values(status="DONE"))
        task = Task(type="INDEX_REBUILD", status="SCANNING", idempotency_key=str(uuid.uuid4()), settings_snapshot={}, counters={}, warnings=[], lease_until=(datetime.now(UTC) - timedelta(minutes=1)).replace(tzinfo=None))
        session.add(task); session.commit(); task_id = task.id
        claimed = claim_one_task(session)
        assert claimed and claimed.id == task_id and claimed.status == "SCANNING"
