import os
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image as PillowImage
from sqlalchemy import delete, select


def make_image(path: Path, color: str) -> None:
    PillowImage.new("RGB", (12, 12), color).save(path)


@pytest.mark.skipif(not os.getenv("MYSQL_TEST_DATABASE_URL"), reason="需要隔离的MySQL测试库")
def test_source_organize_deletes_exact_moves_timestamp_collision_and_keeps_failed_top_level(tmp_path: Path, monkeypatch) -> None:
    database_url = os.environ["MYSQL_TEST_DATABASE_URL"]
    assert "pod_dedup_test" in database_url
    os.environ["DATABASE_URL"] = database_url

    from app.core.db import SessionLocal
    from app.main import app
    from app.models.images import DuplicatePair, FileOperation, Image, ImageFeature, ImageFile, Review, TaskItem
    from app.models.tasks import Task, TaskEvent, TaskResourceLock
    from app.workers.runner import claim_one_task, run_m1_scan

    with SessionLocal() as session:
        for model in (TaskResourceLock, Review, DuplicatePair, FileOperation, ImageFeature, ImageFile, TaskItem, Image, TaskEvent, Task):
            session.execute(delete(model))
        session.commit()

    batch = tmp_path / "260921"
    processed = batch / "已处理"
    library = tmp_path / "source-library"
    pod_library = tmp_path / "pod-library"
    processed.mkdir(parents=True); library.mkdir(); pod_library.mkdir()
    make_image(library / "same.png", "red")
    make_image(library / "20261008112203854.png", "green")
    make_image(processed / "duplicate.png", "red")
    make_image(processed / "same.png", "blue")
    make_image(batch / "failed.png", "green")
    monkeypatch.setattr("app.services.source_organize.timestamped_filename", lambda source: "20261008112203854.png")

    with TestClient(app) as client:
        response = client.post("/api/v1/tasks/source-organize", json={
            "source_batch_dir": str(batch), "source_library_dir": str(library),
            "idempotency_key": str(uuid.uuid4()),
        })
    assert response.status_code == 202
    task_id = int(response.json()["task_id"])

    with SessionLocal() as session:
        task = claim_one_task(session)
        assert task is not None and task.id == task_id
        run_m1_scan(task, session)

    assert not (processed / "duplicate.png").exists()
    assert (library / "same.png").exists()
    assert (library / "20261008112203854.png").exists()
    assert (library / "20261008112203854_1.png").exists()
    assert (batch / "failed.png").exists()
    assert not processed.exists()
    with SessionLocal() as session:
        task = session.get(Task, task_id)
        operations = list(session.scalars(select(FileOperation).where(FileOperation.task_id == task_id)))
        assert task is not None and task.status == "DONE"
        assert {operation.operation for operation in operations} == {"DELETE", "MOVE"}
        assert all(operation.state == "DONE" for operation in operations)
        assert next(operation for operation in operations if operation.operation == "DELETE").thumbnail_path


@pytest.mark.skipif(not os.getenv("MYSQL_TEST_DATABASE_URL"), reason="需要隔离的MySQL测试库")
def test_source_organize_reuses_stale_library_path_record(tmp_path: Path, monkeypatch) -> None:
    """A stale path record must not crash a later verified move into that path."""
    database_url = os.environ["MYSQL_TEST_DATABASE_URL"]
    assert "pod_dedup_test" in database_url
    os.environ["DATABASE_URL"] = database_url

    from app.core.db import SessionLocal
    from app.main import app
    from app.models.images import DuplicatePair, FileOperation, Image as ImageModel, ImageFeature, ImageFile, Review, TaskItem
    from app.models.tasks import Task, TaskEvent, TaskResourceLock
    from app.storage.fingerprint import fingerprint, path_digest
    from app.workers.runner import claim_one_task, run_m1_scan

    with SessionLocal() as session:
        for model in (TaskResourceLock, Review, DuplicatePair, FileOperation, ImageFeature, ImageFile, TaskItem, ImageModel, TaskEvent, Task):
            session.execute(delete(model))
        session.commit()

    batch, processed, library = tmp_path / "batch", tmp_path / "batch" / "已处理", tmp_path / "source-library"
    processed.mkdir(parents=True)
    library.mkdir()
    source = processed / "design.png"
    stale = tmp_path / "stale.png"
    make_image(source, "blue")
    make_image(stale, "red")
    stale_snapshot = fingerprint(stale)
    stale.unlink()
    monkeypatch.setattr("app.services.source_organize.timestamped_filename", lambda source: "20261008112203854.png")

    with SessionLocal() as session:
        old_image = ImageModel(kind="SOURCE", original_filename="design.png", sha256=stale_snapshot.sha256,
                               pixel_digest=stale_snapshot.pixel_digest, width=stale_snapshot.width,
                               height=stale_snapshot.height, file_size=stale_snapshot.size_bytes, status="LIBRARY")
        session.add(old_image)
        session.flush()
        session.add(ImageFile(image_id=old_image.id, role="SOURCE_LIBRARY", path=str(library / "20261008112203854.png"),
                              normalized_path_digest=path_digest(library / "20261008112203854.png"),
                              size_bytes=stale_snapshot.size_bytes, mtime_ns=stale_snapshot.mtime_ns,
                              sha256=stale_snapshot.sha256, file_status="MISSING"))
        session.commit()

    with TestClient(app) as client:
        response = client.post("/api/v1/tasks/source-organize", json={
            "source_batch_dir": str(batch), "source_library_dir": str(library),
            "idempotency_key": str(uuid.uuid4()),
        })
    assert response.status_code == 202
    task_id = int(response.json()["task_id"])
    with SessionLocal() as session:
        task = claim_one_task(session)
        assert task is not None and task.id == task_id
        run_m1_scan(task, session)

    target = library / "20261008112203854.png"
    target_snapshot = fingerprint(target)
    with SessionLocal() as session:
        task = session.get(Task, task_id)
        records = list(session.scalars(select(ImageFile).where(
            ImageFile.normalized_path_digest == path_digest(target)
        )))
        assert task is not None and task.status == "DONE"
        assert len(records) == 1
        assert records[0].sha256 == target_snapshot.sha256
        assert records[0].file_status == "PRESENT"
