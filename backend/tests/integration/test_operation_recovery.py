import os
import uuid
from datetime import date
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import delete


@pytest.mark.skipif(not os.getenv("MYSQL_TEST_DATABASE_URL"), reason="需要隔离的MySQL测试库")
def test_recovery_marks_only_physically_verified_move_done(tmp_path: Path) -> None:
    os.environ["DATABASE_URL"] = os.environ["MYSQL_TEST_DATABASE_URL"]
    from app.core.db import SessionLocal
    from app.models.images import FileOperation
    from app.storage.fingerprint import fingerprint
    from app.storage.safe_ops import reconcile_incomplete_operations

    target = tmp_path / "already-moved.png"
    Image.new("RGB", (30, 40), "red").save(target)
    snapshot = fingerprint(target)
    with SessionLocal() as session:
        session.execute(delete(FileOperation))
        operation = FileOperation(operation="MOVE", origin_path=str(tmp_path / "missing-source.png"), target_path=str(target), origin_sha256=snapshot.sha256, expected_size=snapshot.size_bytes, operation_key="recovery-verified-move", state="EXECUTING", reason="TEST")
        session.add(operation); session.commit(); operation_id = operation.id
        assert reconcile_incomplete_operations(session) == 1
        assert session.get(FileOperation, operation_id).state == "DONE"


@pytest.mark.skipif(not os.getenv("MYSQL_TEST_DATABASE_URL"), reason="需要隔离的MySQL测试库")
def test_pod_archive_recovers_after_move_before_database_checkpoint(tmp_path: Path) -> None:
    """A pre-persisted destination lets a restart finish an interrupted archive."""
    os.environ["DATABASE_URL"] = os.environ["MYSQL_TEST_DATABASE_URL"]
    from app.core.db import SessionLocal
    from app.models.images import DuplicatePair, FileOperation, Image as ImageModel, ImageFeature, ImageFile, Review, TaskItem, VlmCall
    from app.models.tasks import Task, TaskEvent, TaskResourceLock
    from app.services.pod_dedup import archive_ready_items
    from app.services.source_organize import _operation
    from app.storage.fingerprint import fingerprint, path_digest
    from app.storage.safe_ops import move_verified, plan_target

    with SessionLocal() as session:
        for model in (VlmCall, Review, DuplicatePair, FileOperation, ImageFeature, ImageFile, TaskItem, ImageModel, TaskResourceLock, TaskEvent, Task):
            session.execute(delete(model))
        session.commit()
    pending, library = tmp_path / "pending", tmp_path / "library"
    pending.mkdir(); library.mkdir()
    source = pending / "design.png"
    Image.new("RGB", (30, 40), "red").save(source)
    snapshot = fingerprint(source)
    with SessionLocal() as session:
        task = Task(type="POD_DEDUP", status="ARCHIVING", pod_pending_dir=str(pending), pod_library_dir=str(library), ratio_code="3x4", archive_date=date(2026, 9, 22), idempotency_key=str(uuid.uuid4()), settings_snapshot={}, counters={}, warnings=[])
        image = ImageModel(kind="POD", original_filename=source.name, sha256=snapshot.sha256, pixel_digest=snapshot.pixel_digest, width=snapshot.width, height=snapshot.height, file_size=snapshot.size_bytes, status="PENDING")
        session.add_all((task, image)); session.flush()
        item = TaskItem(task_id=task.id, image_id=image.id, observed_path=str(source), observed_path_digest=path_digest(source), stage="ARCHIVING", status="READY_TO_ARCHIVE", snapshot_sha256=snapshot.sha256, snapshot_size=snapshot.size_bytes, snapshot_mtime_ns=snapshot.mtime_ns)
        pending_file = ImageFile(image_id=image.id, role="POD_PENDING", path=str(source), normalized_path_digest=path_digest(source), size_bytes=snapshot.size_bytes, mtime_ns=snapshot.mtime_ns, sha256=snapshot.sha256, file_status="PRESENT")
        session.add_all((item, pending_file)); session.commit()

        planned = plan_target(library, source.name, snapshot.sha256)
        move_operation = _operation(session, task, item, image, "MOVE", source, snapshot, "POD_MASTER_ARCHIVE", planned)
        move_operation.state = "EXECUTING"; session.commit()
        move_verified(source, library, snapshot, target=planned)

        archived, failures = archive_ready_items(task, session, tmp_path / "thumbs")
        session.commit()
        assert archived == 1 and failures == 0
        assert session.get(FileOperation, move_operation.id).state == "DONE"
        refreshed_file = session.get(ImageFile, pending_file.id)
        assert refreshed_file and refreshed_file.role == "POD_MASTER" and Path(refreshed_file.path) == planned
        assert session.query(ImageFile).filter(ImageFile.image_id == image.id, ImageFile.role == "POD_CLASSIFIED", ImageFile.file_status == "PRESENT").count() == 1
    assert not source.exists() and planned.exists()


@pytest.mark.skipif(not os.getenv("MYSQL_TEST_DATABASE_URL"), reason="需要隔离的MySQL测试库")
def test_source_organize_recovers_after_move_before_database_checkpoint(tmp_path: Path) -> None:
    os.environ["DATABASE_URL"] = os.environ["MYSQL_TEST_DATABASE_URL"]
    from app.core.db import SessionLocal
    from app.models.images import DuplicatePair, FileOperation, Image as ImageModel, ImageFeature, ImageFile, Review, TaskItem, VlmCall
    from app.models.tasks import Task, TaskEvent, TaskResourceLock
    from app.services.source_organize import _operation, organize
    from app.storage.fingerprint import fingerprint, path_digest
    from app.storage.safe_ops import move_verified, plan_target

    with SessionLocal() as session:
        for model in (VlmCall, Review, DuplicatePair, FileOperation, ImageFeature, ImageFile, TaskItem, ImageModel, TaskResourceLock, TaskEvent, Task):
            session.execute(delete(model))
        session.commit()
    batch, processed, library = tmp_path / "batch", tmp_path / "batch" / "已处理", tmp_path / "library"
    processed.mkdir(parents=True); library.mkdir()
    source = processed / "source.png"
    Image.new("RGB", (30, 40), "blue").save(source)
    snapshot = fingerprint(source)
    with SessionLocal() as session:
        task = Task(type="SOURCE_ORGANIZE", status="SOURCE_ORGANIZING", source_batch_dir=str(batch), source_library_dir=str(library), idempotency_key=str(uuid.uuid4()), settings_snapshot={}, counters={}, warnings=[])
        image = ImageModel(kind="SOURCE", original_filename=source.name, sha256=snapshot.sha256, pixel_digest=snapshot.pixel_digest, width=snapshot.width, height=snapshot.height, file_size=snapshot.size_bytes, status="PENDING")
        session.add_all((task, image)); session.flush()
        item = TaskItem(task_id=task.id, image_id=image.id, observed_path=str(source), observed_path_digest=path_digest(source), stage="SOURCE_ORGANIZING", status="MOVING", snapshot_sha256=snapshot.sha256, snapshot_size=snapshot.size_bytes, snapshot_mtime_ns=snapshot.mtime_ns)
        session.add(item); session.commit()
        planned = plan_target(library, source.name, snapshot.sha256)
        operation = _operation(session, task, item, image, "MOVE", source, snapshot, "SOURCE_PROCESSED_TO_LIBRARY", planned)
        operation.state = "EXECUTING"; session.commit()
        move_verified(source, library, snapshot, target=planned)

        assert organize(task, session, tmp_path / "thumbs") == 0
        assert session.get(FileOperation, operation.id).state == "DONE"
        assert session.get(TaskItem, item.id).status == "ARCHIVED_SOURCE"
        assert session.get(ImageModel, image.id).status == "LIBRARY"
        assert session.query(ImageFile).filter(ImageFile.image_id == image.id, ImageFile.role == "SOURCE_LIBRARY", ImageFile.file_status == "PRESENT").count() == 1
    assert planned.exists() and not source.exists()
