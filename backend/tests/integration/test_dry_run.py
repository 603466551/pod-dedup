import os
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import delete, select


@pytest.mark.skipif(not os.getenv("MYSQL_TEST_DATABASE_URL"), reason="需要隔离的MySQL测试库")
def test_pod_dry_run_never_moves_or_deletes_files(tmp_path: Path) -> None:
    os.environ["DATABASE_URL"] = os.environ["MYSQL_TEST_DATABASE_URL"]
    from app.core.db import SessionLocal
    from app.main import app
    from app.models.images import DuplicatePair, FileOperation, Image as ImageModel, ImageFeature, ImageFile, Review, TaskItem
    from app.models.tasks import Task, TaskEvent, TaskResourceLock
    from app.workers.runner import claim_one_task, run_m1_scan

    with SessionLocal() as session:
        for model in (TaskResourceLock, Review, DuplicatePair, FileOperation, ImageFeature, ImageFile, TaskItem, ImageModel, TaskEvent, Task):
            session.execute(delete(model))
        session.commit()
    batch, source_library, pending, library = (tmp_path / name for name in ("batch", "source", "pending", "library"))
    for directory in (batch, source_library, pending, library):
        directory.mkdir()
    candidate = pending / "keep.png"
    Image.new("RGB", (300, 400), "green").save(candidate)
    with TestClient(app) as client:
        created = client.post("/api/v1/tasks/pod-dedup", json={"source_batch_dir": str(batch), "source_library_dir": str(source_library), "pod_pending_dir": str(pending), "pod_library_dir": str(library), "ratio_code": "3x4", "dry_run": True, "idempotency_key": str(uuid.uuid4())})
    assert created.status_code == 202
    with SessionLocal() as session:
        task = claim_one_task(session)
        assert task is not None
        run_m1_scan(task, session)
    assert candidate.exists()
    assert not (library / candidate.name).exists()
    with SessionLocal() as session:
        task = session.get(Task, int(created.json()["task_id"]))
        item = session.scalar(select(TaskItem).where(TaskItem.task_id == task.id))
        assert task and task.status == "DONE"
        assert item and item.status == "WOULD_ARCHIVE"
        assert session.query(FileOperation).filter(FileOperation.task_id == task.id).count() == 0
