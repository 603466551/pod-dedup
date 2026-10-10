import os
import uuid
from datetime import date, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image as PillowImage
from PIL import ImageDraw
from sqlalchemy import delete, select


def make_design(path: Path, text: str, *, jpeg: bool = False) -> None:
    image = PillowImage.new("RGB", (300, 400), "#f4e7c5")
    draw = ImageDraw.Draw(image)
    draw.rectangle((30, 30, 270, 370), outline="#224466", width=12)
    draw.ellipse((75, 100, 225, 250), fill="#d04d55", outline="#223344", width=6)
    draw.text((105, 290), text, fill="#112233", stroke_width=1)
    image.save(path, quality=78) if jpeg else image.save(path)


def clear_database(session) -> None:
    from app.models.images import DuplicatePair, FileOperation, Image, ImageFeature, ImageFile, Review, TaskItem
    from app.models.tasks import Task, TaskEvent, TaskResourceLock

    for model in (TaskResourceLock, Review, DuplicatePair, FileOperation, ImageFeature, ImageFile, TaskItem, Image, TaskEvent, Task):
        session.execute(delete(model))
    session.commit()


def run_pod_task(client, session_factory, *, batch: Path, source_library: Path, pending: Path, library: Path) -> int:
    response = client.post("/api/v1/tasks/pod-dedup", json={"source_batch_dir": str(batch), "source_library_dir": str(source_library), "pod_pending_dir": str(pending), "pod_library_dir": str(library), "ratio_code": "3x4", "idempotency_key": str(uuid.uuid4())})
    assert response.status_code == 202
    from app.workers.runner import claim_one_task, run_m1_scan

    with session_factory() as session:
        task = claim_one_task(session)
        assert task is not None
        run_m1_scan(task, session)
    return int(response.json()["task_id"])


@pytest.mark.skipif(not os.getenv("MYSQL_TEST_DATABASE_URL"), reason="需要隔离的MySQL测试库")
def test_recompressed_pod_creates_review_and_classified_copy_is_not_a_master(tmp_path: Path, monkeypatch) -> None:
    os.environ["DATABASE_URL"] = os.environ["MYSQL_TEST_DATABASE_URL"]
    from app.core.db import SessionLocal
    from app.main import app
    from app.models.images import DuplicatePair, Image, Review
    from app.models.tasks import Task

    with SessionLocal() as session:
        clear_database(session)
    monkeypatch.setattr("app.services.pod_dedup.timestamped_filename", lambda source: f"20261008112203854{source.suffix}")
    batch, source_library, pending, library = (tmp_path / name for name in ("source-batch", "source-library", "pending", "pod-library"))
    for directory in (batch, source_library, pending, library):
        directory.mkdir()
    make_design(library / "kept.png", "POD")
    classified = library / "Portrait" / "3x4" / "260921" / "kept.png"
    classified.parent.mkdir(parents=True)
    make_design(classified, "POD")
    make_design(pending / "renamed-recompressed.jpg", "POD", jpeg=True)

    with TestClient(app) as client:
        task_id = run_pod_task(client, SessionLocal, batch=batch, source_library=source_library, pending=pending, library=library)
    assert (pending / "renamed-recompressed.jpg").exists()
    with SessionLocal() as session:
        task = session.get(Task, task_id)
        pairs = list(session.scalars(select(DuplicatePair).where(DuplicatePair.task_id == task_id)))
        assert task and task.status == "WAIT_REVIEW"
        assert task.archive_date is None
        assert len(pairs) == 1 and pairs[0].machine_decision == "RETRIEVED_CANDIDATE"
        assert pairs[0].evidence_json["cosine_similarity"] > 0.85
        assert session.query(Review).filter(Review.task_id == task_id).count() == 1
        assert session.query(Image).filter(Image.kind == "POD").count() == 2
        review_id = session.scalar(select(Review.id).where(Review.task_id == task_id))
    class ArchiveDay:
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 22, 10, 0, tzinfo=tz)
    monkeypatch.setattr("app.services.pod_dedup.datetime", ArchiveDay)
    with TestClient(app) as client:
        resolved = client.post(f"/api/v1/reviews/{review_id}/decision", json={"duplicate_decision": "NOT_DUPLICATE", "action_decision": "KEEP_BOTH", "confirm_delete": False, "version": 1})
        records = client.get(f"/api/v1/duplicate-records?task_id={task_id}")
    assert resolved.status_code == 200
    assert records.status_code == 200 and records.json()["items"][0]["human_decision"]["duplicate"] == "NOT_DUPLICATE"
    assert not (pending / "renamed-recompressed.jpg").exists()
    assert (library / "20261008112203854.jpg").exists()
    with SessionLocal() as session:
        task = session.get(Task, task_id)
        assert task and task.status == "DONE"
        assert task.archive_date == date(2026, 9, 22)
        assert (library / "Portrait" / "3x4" / task.archive_date.strftime("%y%m%d") / "20261008112203854.jpg").exists()


@pytest.mark.skipif(not os.getenv("MYSQL_TEST_DATABASE_URL"), reason="需要隔离的MySQL测试库")
def test_different_text_candidate_is_never_auto_deleted(tmp_path: Path, monkeypatch) -> None:
    os.environ["DATABASE_URL"] = os.environ["MYSQL_TEST_DATABASE_URL"]
    from app.core.config import settings
    from app.core.db import SessionLocal
    from app.main import app
    from app.models.images import DuplicatePair, Review
    from app.models.tasks import Task

    # This test deliberately broadens recall.  The assertion is that recall
    # still cannot become an automatic deletion decision.
    monkeypatch.setattr(settings, "retrieval_candidate_min_similarity", -1.0)
    with SessionLocal() as session:
        clear_database(session)
    batch, source_library, pending, library = (tmp_path / name for name in ("source-batch", "source-library", "pending", "pod-library"))
    for directory in (batch, source_library, pending, library):
        directory.mkdir()
    make_design(library / "old.png", "SALE")
    make_design(pending / "different-text.png", "NEW")

    with TestClient(app) as client:
        task_id = run_pod_task(client, SessionLocal, batch=batch, source_library=source_library, pending=pending, library=library)
    assert (pending / "different-text.png").exists()
    with SessionLocal() as session:
        task = session.get(Task, task_id)
        pair = session.scalar(select(DuplicatePair).where(DuplicatePair.task_id == task_id))
        assert task and task.status == "WAIT_REVIEW"
        assert pair and pair.machine_decision == "RETRIEVED_CANDIDATE"
        assert pair.resolution_status == "PENDING"
        assert session.query(Review).filter(Review.task_id == task_id).count() == 1


@pytest.mark.skipif(not os.getenv("MYSQL_TEST_DATABASE_URL"), reason="需要隔离的MySQL测试库")
def test_cross_ratio_visual_candidate_is_recorded_without_review_or_auto_delete(tmp_path: Path) -> None:
    os.environ["DATABASE_URL"] = os.environ["MYSQL_TEST_DATABASE_URL"]
    from app.core.db import SessionLocal
    from app.models.images import DuplicatePair, Image, Review, TaskItem
    from app.models.tasks import Task
    from app.services.pod_dedup import _create_visual_reviews

    with SessionLocal() as session:
        clear_database(session)
        task = Task(type="POD_DEDUP", status="POD_SEARCH", ratio_code="9x16", idempotency_key=str(uuid.uuid4()), settings_snapshot={}, counters={}, warnings=[])
        new = Image(kind="POD", original_filename="new.png", sha256=b"n" * 32, status="PENDING")
        old = Image(kind="POD", original_filename="old.png", sha256=b"o" * 32, status="LIBRARY")
        session.add_all((task, new, old)); session.flush()
        item = TaskItem(task_id=task.id, image_id=new.id, observed_path=str(tmp_path / "new.png"), observed_path_digest=b"p" * 32, stage="DECIDING", status="CHECKING")
        session.add(item); session.flush()
        created = _create_visual_reviews(task, item, new, tmp_path / "new.png", [{"image_id": old.id, "feature_id": 1, "score": 0.99, "path": str(tmp_path / "old.png"), "ratio_code": "3x4"}], session)
        session.commit()
        pair = session.query(DuplicatePair).filter(DuplicatePair.task_id == task.id).one()
        assert created == 0
        assert pair.resolution_status == "RATIO_PROTECTED" and pair.review_required is False
        assert session.query(Review).filter(Review.task_id == task.id).count() == 0


@pytest.mark.skipif(not os.getenv("MYSQL_TEST_DATABASE_URL"), reason="需要隔离的MySQL测试库")
def test_resolved_nonduplicate_content_pair_is_reused_without_new_review(tmp_path: Path) -> None:
    os.environ["DATABASE_URL"] = os.environ["MYSQL_TEST_DATABASE_URL"]
    from app.core.db import SessionLocal
    from app.models.images import DuplicatePair, Image, Review, TaskItem
    from app.models.tasks import Task
    from app.services.pod_dedup import _create_visual_reviews

    with SessionLocal() as session:
        clear_database(session)
        old = Image(kind="POD", original_filename="old.png", sha256=b"o" * 32, status="LIBRARY")
        first = Image(kind="POD", original_filename="first.png", sha256=b"n" * 32, status="LIBRARY")
        first_task = Task(type="POD_DEDUP", status="DONE", ratio_code="3x4", idempotency_key=str(uuid.uuid4()), settings_snapshot={}, counters={}, warnings=[])
        session.add_all((old, first, first_task)); session.flush()
        first_pair = DuplicatePair(task_id=first_task.id, image_new_id=first.id, image_match_id=old.id, pair_type="POD_POD", machine_decision="RETRIEVED_CANDIDATE", rule_id="TEST", evidence_json={}, review_required=True, resolution_status="RESOLVED")
        session.add(first_pair); session.flush()
        session.add(Review(task_id=first_task.id, pair_id=first_pair.id, status="RESOLVED", duplicate_decision="NOT_DUPLICATE", action_decision="KEEP_BOTH", version=2)); session.commit()

        task = Task(type="POD_DEDUP", status="POD_SEARCH", ratio_code="3x4", idempotency_key=str(uuid.uuid4()), settings_snapshot={}, counters={}, warnings=[])
        again = Image(kind="POD", original_filename="again.png", sha256=b"n" * 32, status="PENDING")
        session.add_all((task, again)); session.flush()
        item = TaskItem(task_id=task.id, image_id=again.id, observed_path=str(tmp_path / "again.png"), observed_path_digest=b"r" * 32, stage="DECIDING", status="CHECKING")
        session.add(item); session.flush()
        created = _create_visual_reviews(task, item, again, tmp_path / "again.png", [{"image_id": old.id, "feature_id": 1, "score": 0.99, "path": str(tmp_path / "old.png"), "ratio_code": "3x4"}], session)
        session.commit()
        reused = session.query(DuplicatePair).filter(DuplicatePair.task_id == task.id).one()
        assert created == 0
        assert reused.machine_decision == "REUSED_HUMAN_DECISION" and reused.resolution_status == "RESOLVED_REUSED"
        assert session.query(Review).filter(Review.task_id == task.id).count() == 0
