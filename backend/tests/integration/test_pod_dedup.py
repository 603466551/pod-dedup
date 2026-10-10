import os
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image as PillowImage
from sqlalchemy import delete, select


def make_image(path: Path, color: str, size: tuple[int, int]) -> None:
    PillowImage.new("RGB", size, color).save(path)


@pytest.mark.skipif(not os.getenv("MYSQL_TEST_DATABASE_URL"), reason="需要隔离的MySQL测试库")
def test_pod_exact_duplicate_archives_all_input_ratios(tmp_path: Path, monkeypatch) -> None:
    database_url = os.environ["MYSQL_TEST_DATABASE_URL"]
    assert "pod_dedup_test" in database_url
    os.environ["DATABASE_URL"] = database_url
    from app.core.db import SessionLocal
    from app.main import app
    from app.core.config import settings
    from app.models.images import DuplicatePair, FileOperation, Image, ImageFeature, ImageFile, Review, TaskItem
    from app.models.tasks import Task, TaskEvent, TaskResourceLock
    from app.workers.runner import claim_one_task, run_m1_scan
    with SessionLocal() as session:
        for model in (TaskResourceLock, Review, DuplicatePair, FileOperation, ImageFeature, ImageFile, TaskItem, Image, TaskEvent, Task): session.execute(delete(model))
        session.commit()
    monkeypatch.setattr(settings, "retrieval_candidate_min_similarity", 1.0)
    monkeypatch.setattr("app.services.pod_dedup.timestamped_filename", lambda source: f"20261008112203854{source.suffix}")
    batch, source_library, pending, library = tmp_path / "source-batch", tmp_path / "source-library", tmp_path / "pending", tmp_path / "pod-library"
    for directory in (batch, source_library, pending, library): directory.mkdir()
    make_image(library / "old.png", "red", (30, 40))
    make_image(pending / "duplicate.png", "red", (30, 40))
    make_image(pending / "new.png", "blue", (30, 40))
    make_image(pending / "wrong.png", "green", (10, 10))
    with TestClient(app) as client:
        response = client.post("/api/v1/tasks/pod-dedup", json={"pod_pending_dir": str(pending), "pod_library_dir": str(library), "ratio_code": "3x4", "idempotency_key": str(uuid.uuid4())})
    assert response.status_code == 202
    with SessionLocal() as session:
        task = claim_one_task(session); assert task and task.id == int(response.json()["task_id"]); run_m1_scan(task, session)
    assert not (pending / "duplicate.png").exists()
    assert not (pending / "new.png").exists()
    assert not (pending / "wrong.png").exists()
    assert (library / "20261008112203854.png").exists()
    with SessionLocal() as session:
        task = session.get(Task, int(response.json()["task_id"])); assert task and task.status == "DONE" and task.archive_date
        events = list(session.scalars(select(TaskEvent).where(TaskEvent.task_id == task.id)))
        assert not list((library / "Portrait").rglob("*.png")) if (library / "Portrait").exists() else True
        files = list(session.scalars(select(ImageFile).where(ImageFile.role == "POD_CLASSIFIED")))
        operations = list(session.scalars(select(FileOperation).where(FileOperation.task_id == task.id)))
        assert len(files) == 0 and len(operations) == 3
        assert {operation.operation for operation in operations} == {"DELETE", "MOVE"}
        assert all(operation.state == "DONE" for operation in operations)
        assert any("MJ POD直入模式" in event.message for event in events)


@pytest.mark.skipif(not os.getenv("MYSQL_TEST_DATABASE_URL"), reason="需要隔离的MySQL测试库")
def test_pod_frozen_manifest_excludes_later_arrivals(tmp_path: Path, monkeypatch) -> None:
    os.environ["DATABASE_URL"] = os.environ["MYSQL_TEST_DATABASE_URL"]
    from app.core.config import settings
    from app.core.db import SessionLocal
    from app.models.images import DuplicatePair, FileOperation, Image, ImageFeature, ImageFile, Review, TaskItem
    from app.models.tasks import Task, TaskEvent, TaskResourceLock
    from app.services.pod_dedup import _frozen_manifest, deduplicate_and_archive

    monkeypatch.setattr(settings, "retrieval_candidate_min_similarity", 1.0)
    monkeypatch.setattr("app.services.pod_dedup.timestamped_filename", lambda source: f"20261008112203854{source.suffix}")
    with SessionLocal() as session:
        for model in (TaskResourceLock, Review, DuplicatePair, FileOperation, ImageFeature, ImageFile, TaskItem, Image, TaskEvent, Task):
            session.execute(delete(model))
        session.commit()
    batch, source_library, pending, library = (tmp_path / name for name in ("batch", "source", "pending", "library"))
    for directory in (batch, source_library, pending, library): directory.mkdir()
    make_image(pending / "frozen.png", "red", (30, 40))
    with SessionLocal() as session:
        task = Task(type="POD_DEDUP", status="SCANNING", source_batch_dir=str(batch), source_library_dir=str(source_library), pod_pending_dir=str(pending), pod_library_dir=str(library), ratio_code="3x4", idempotency_key=str(uuid.uuid4()), settings_snapshot={}, counters={}, warnings=[])
        session.add(task); session.commit()
        _frozen_manifest(task, pending, session)
        make_image(pending / "late.png", "blue", (30, 40))
        deduplicate_and_archive(task, session, tmp_path / "thumbs")
    assert (library / "20261008112203854.png").exists()
    assert (pending / "late.png").exists()
