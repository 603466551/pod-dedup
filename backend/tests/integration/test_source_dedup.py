import os
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image as PillowImage
from sqlalchemy import delete, select


def make_image(path: Path, color: str) -> None:
    PillowImage.new("RGB", (10, 10), color).save(path)


@pytest.mark.skipif(not os.getenv("MYSQL_TEST_DATABASE_URL"), reason="需要隔离的MySQL测试库")
def test_source_dedup_checks_history_and_current_batch_exactly(tmp_path: Path) -> None:
    database_url = os.environ["MYSQL_TEST_DATABASE_URL"]
    assert "pod_dedup_test" in database_url
    os.environ["DATABASE_URL"] = database_url
    from app.core.db import SessionLocal
    from app.main import app
    from app.models.images import DuplicatePair, FileOperation, Image, ImageFeature, ImageFile, Review, TaskItem
    from app.models.tasks import Task, TaskEvent, TaskResourceLock
    from app.workers.runner import claim_one_task, run_m1_scan
    with SessionLocal() as session:
        for model in (TaskResourceLock, Review, DuplicatePair, FileOperation, ImageFeature, ImageFile, TaskItem, Image, TaskEvent, Task): session.execute(delete(model))
        session.commit()
    batch, source_library = tmp_path / "batch", tmp_path / "source"
    batch.mkdir(); source_library.mkdir()
    make_image(source_library / "old.png", "red")
    make_image(batch / "history-duplicate.png", "red")
    make_image(batch / "a-first.png", "blue")
    make_image(batch / "z-batch-duplicate.png", "blue")
    with TestClient(app) as client:
        response = client.post("/api/v1/tasks/source-dedup", json={"source_batch_dir": str(batch), "source_library_dir": str(source_library), "dry_run": False, "idempotency_key": str(uuid.uuid4())})
    with SessionLocal() as session:
        task = claim_one_task(session); assert task and task.id == int(response.json()["task_id"]); run_m1_scan(task, session)
    assert (batch / "a-first.png").exists()
    assert not (batch / "history-duplicate.png").exists() and not (batch / "z-batch-duplicate.png").exists()
    with SessionLocal() as session:
        task = session.get(Task, int(response.json()["task_id"])); operations = list(session.scalars(select(FileOperation)))
        assert task and task.status == "DONE" and task.counters["deleted"] == 2
        assert len(operations) == 2 and all(operation.thumbnail_path for operation in operations)
