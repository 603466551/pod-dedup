import os
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image as PillowImage
from sqlalchemy import delete
from sqlalchemy import select


@pytest.mark.skipif(not os.getenv("MYSQL_TEST_DATABASE_URL"), reason="需要隔离的MySQL测试库")
def test_review_delete_match_removes_master_and_classified_copy(tmp_path: Path) -> None:
    os.environ["DATABASE_URL"] = os.environ["MYSQL_TEST_DATABASE_URL"]
    from app.core.db import SessionLocal
    from app.main import app
    from app.models.images import DuplicatePair, FileOperation, Image, ImageFeature, ImageFile, Review, TaskItem
    from app.models.tasks import Task, TaskEvent, TaskResourceLock
    from app.storage.fingerprint import fingerprint, path_digest
    with SessionLocal() as session:
        for model in (TaskResourceLock, Review, DuplicatePair, FileOperation, ImageFeature, ImageFile, TaskItem, Image, TaskEvent, Task): session.execute(delete(model))
        task = Task(type="POD_DEDUP", status="WAIT_REVIEW", pod_library_dir=str(tmp_path), idempotency_key="review-delete-test", settings_snapshot={}, counters={}, warnings=[])
        session.add(task); session.flush()
        new = Image(kind="POD", original_filename="new.png", status="PENDING")
        old = Image(kind="POD", original_filename="old.png", status="LIBRARY")
        session.add_all([new, old]); session.flush()
        master, classified = tmp_path / "old.png", tmp_path / "Portrait" / "3x4" / "260921" / "old.png"; classified.parent.mkdir(parents=True)
        classified_second = tmp_path / "Landscape" / "4x3" / "260920" / "old.png"; classified_second.parent.mkdir(parents=True)
        unregistered = tmp_path / "Square" / "1x1" / "260919" / "old.png"; unregistered.parent.mkdir(parents=True)
        missing_production = tmp_path / "Production" / "1x1" / "260921" / "old_1x1.png"; missing_production.parent.mkdir(parents=True)
        for path in (master, classified, classified_second, unregistered): PillowImage.new("RGB", (30, 40), "red").save(path)
        for path, role in ((master, "POD_MASTER"), (classified, "POD_CLASSIFIED"), (classified_second, "POD_CLASSIFIED")):
            snap = fingerprint(path); session.add(ImageFile(image_id=old.id, role=role, path=str(path), normalized_path_digest=path_digest(path), size_bytes=snap.size_bytes, mtime_ns=snap.mtime_ns, sha256=snap.sha256, file_status="PRESENT"))
        master_snapshot = fingerprint(master)
        session.add(ImageFile(image_id=old.id, role="POD_PRODUCTION", path=str(missing_production), normalized_path_digest=path_digest(missing_production), size_bytes=master_snapshot.size_bytes, mtime_ns=master_snapshot.mtime_ns, sha256=master_snapshot.sha256, file_status="PRESENT"))
        pair = DuplicatePair(task_id=task.id, image_new_id=new.id, image_match_id=old.id, pair_type="POD_POD", machine_decision="UNCERTAIN", rule_id="TEST", evidence_json={}, review_required=True, resolution_status="PENDING")
        session.add(pair); session.flush(); review = Review(pair_id=pair.id, task_id=task.id, status="PENDING", version=1); session.add(review); session.commit(); review_id = review.id; task_id = task.id; old_id = old.id
    with TestClient(app) as client:
        detail = client.get(f"/api/v1/reviews/{review_id}")
        rejected = client.post(f"/api/v1/reviews/{review_id}/decision", json={"duplicate_decision":"DUPLICATE","action_decision":"DELETE_MATCH","confirm_delete":False,"version":1})
        accepted = client.post(f"/api/v1/reviews/{review_id}/decision", json={"duplicate_decision":"DUPLICATE","action_decision":"DELETE_MATCH","confirm_delete":True,"version":1})
        repeated = client.post(f"/api/v1/reviews/{review_id}/decision", json={"duplicate_decision":"DUPLICATE","action_decision":"DELETE_MATCH","confirm_delete":True,"version":1})
    assert detail.status_code == 200 and detail.json()["match_image"]["filename"] == "old.png"
    assert rejected.status_code == 422 and accepted.status_code == 200
    assert repeated.status_code == 409 and repeated.json()["detail"]["code"] == "REVIEW_NOT_PENDING"
    assert not master.exists() and not classified.exists() and not classified_second.exists()
    assert unregistered.exists()
    with SessionLocal() as session:
        assert session.query(FileOperation).count() == 3
        assert "UNREGISTERED_CLASSIFIED_COPY:1" in session.get(Task, task_id).warnings
        production = session.scalar(select(ImageFile).where(ImageFile.image_id == old_id, ImageFile.role == "POD_PRODUCTION"))
        assert production and production.file_status == "MISSING"


@pytest.mark.skipif(not os.getenv("MYSQL_TEST_DATABASE_URL"), reason="需要隔离的MySQL测试库")
def test_delete_new_resolves_other_pending_reviews_for_the_same_new_image(tmp_path: Path) -> None:
    os.environ["DATABASE_URL"] = os.environ["MYSQL_TEST_DATABASE_URL"]
    from app.core.db import SessionLocal
    from app.main import app
    from app.models.images import DuplicatePair, FileOperation, Image, ImageFeature, ImageFile, Review, TaskItem
    from app.models.tasks import Task, TaskEvent, TaskResourceLock
    from app.storage.fingerprint import fingerprint, path_digest

    with SessionLocal() as session:
        for model in (TaskResourceLock, Review, DuplicatePair, FileOperation, ImageFeature, ImageFile, TaskItem, Image, TaskEvent, Task):
            session.execute(delete(model))
        task = Task(type="POD_DEDUP", status="WAIT_REVIEW", pod_library_dir=str(tmp_path), idempotency_key=str(uuid.uuid4()), settings_snapshot={}, counters={}, warnings=[])
        session.add(task); session.flush()
        new, old_a, old_b = Image(kind="POD", original_filename="new.png", status="PENDING"), Image(kind="POD", original_filename="old-a.png", status="LIBRARY"), Image(kind="POD", original_filename="old-b.png", status="LIBRARY")
        session.add_all((new, old_a, old_b)); session.flush()
        new_path = tmp_path / "new.png"; PillowImage.new("RGB", (30, 40), "blue").save(new_path)
        snap = fingerprint(new_path)
        session.add(ImageFile(image_id=new.id, role="POD_PENDING", path=str(new_path), normalized_path_digest=path_digest(new_path), size_bytes=snap.size_bytes, mtime_ns=snap.mtime_ns, sha256=snap.sha256, file_status="PRESENT"))
        first = DuplicatePair(task_id=task.id, image_new_id=new.id, image_match_id=old_a.id, pair_type="POD_POD", machine_decision="RETRIEVED_CANDIDATE", rule_id="TEST", evidence_json={}, review_required=True, resolution_status="PENDING")
        second = DuplicatePair(task_id=task.id, image_new_id=new.id, image_match_id=old_b.id, pair_type="POD_POD", machine_decision="RETRIEVED_CANDIDATE", rule_id="TEST", evidence_json={}, review_required=True, resolution_status="PENDING")
        session.add_all((first, second)); session.flush()
        review = Review(pair_id=first.id, task_id=task.id, status="PENDING", version=1)
        session.add_all((review, Review(pair_id=second.id, task_id=task.id, status="PENDING", version=1)))
        session.commit(); review_id = review.id; second_pair_id = second.id

    with TestClient(app) as client:
        response = client.post(f"/api/v1/reviews/{review_id}/decision", json={"duplicate_decision":"DUPLICATE", "action_decision":"DELETE_NEW", "confirm_delete":True, "version":1})
    assert response.status_code == 200 and not new_path.exists()
    with SessionLocal() as session:
        statuses = list(session.scalars(select(Review.status).order_by(Review.id)))
        second_pair = session.get(DuplicatePair, second_pair_id)
        assert statuses == ["RESOLVED", "RESOLVED"]
        assert second_pair and second_pair.resolution_status == "RESOLVED_BY_DELETION"
