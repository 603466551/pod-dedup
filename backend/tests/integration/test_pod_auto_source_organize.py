import os
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image as PillowImage
from sqlalchemy import delete


def make_image(path: Path, color: str, size: tuple[int, int]) -> None:
    PillowImage.new("RGB", size, color).save(path)


@pytest.mark.skipif(not os.getenv("MYSQL_TEST_DATABASE_URL"), reason="需要隔离的MySQL测试库")
def test_pod_task_organizes_processed_sources_before_archiving(tmp_path: Path, monkeypatch) -> None:
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
    batch, source_library, pending, pod_library = tmp_path / "batch", tmp_path / "source-library", tmp_path / "pending", tmp_path / "pod-library"
    (batch / "已处理").mkdir(parents=True); source_library.mkdir(); pending.mkdir(); pod_library.mkdir()
    make_image(source_library / "known.png", "red", (12, 12))
    make_image(batch / "已处理" / "finished.png", "red", (12, 12))
    make_image(pending / "pod.png", "blue", (30, 40))
    monkeypatch.setattr("app.services.pod_dedup.timestamped_filename", lambda source: f"20261008112203854{source.suffix}")
    with TestClient(app) as client:
        response = client.post("/api/v1/tasks/pod-dedup", json={"source_batch_dir": str(batch), "source_library_dir": str(source_library), "pod_pending_dir": str(pending), "pod_library_dir": str(pod_library), "ratio_code": "3x4", "idempotency_key": str(uuid.uuid4())})
    with SessionLocal() as session:
        task = claim_one_task(session); assert task; run_m1_scan(task, session)
    assert not (source_library / "finished.png").exists()
    assert (source_library / "known.png").exists()
    assert not (batch / "已处理").exists()
    assert (pod_library / "20261008112203854.png").exists()
    with SessionLocal() as session:
        task = session.get(Task, int(response.json()["task_id"]))
        assert task is not None
        assert task.counters["deleted"] == 1
        assert task.counters["processed"] == 2
