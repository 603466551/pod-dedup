import os
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image as PillowImage
from PIL import ImageDraw
from sqlalchemy import delete, select


def make_source(path: Path, text: str) -> None:
    image = PillowImage.new("RGB", (500, 600), "#eef1f4")
    draw = ImageDraw.Draw(image)
    draw.rectangle((90, 100, 410, 500), fill="#f7d6a0", outline="#1d4266", width=14)
    draw.ellipse((150, 180, 350, 370), fill="#c13f52", outline="#1d4266", width=8)
    draw.text((210, 420), text, fill="#172b40", stroke_width=1)
    image.save(path)


def clear_database(session) -> None:
    from app.models.images import DuplicatePair, FileOperation, Image, ImageFeature, ImageFile, Review, TaskItem
    from app.models.tasks import Task, TaskEvent, TaskResourceLock

    for model in (TaskResourceLock, Review, DuplicatePair, FileOperation, ImageFeature, ImageFile, TaskItem, Image, TaskEvent, Task):
        session.execute(delete(model))
    session.commit()


@pytest.mark.skipif(not os.getenv("MYSQL_TEST_DATABASE_URL"), reason="需要隔离的MySQL测试库")
def test_source_print_roi_queries_source_library_and_keeps_new_text(tmp_path: Path, monkeypatch) -> None:
    os.environ["DATABASE_URL"] = os.environ["MYSQL_TEST_DATABASE_URL"]
    from app.core.config import settings
    from app.core.db import SessionLocal
    from app.main import app
    from app.models.images import DuplicatePair, ImageFeature
    from app.models.tasks import Task

    monkeypatch.setattr(settings, "retrieval_candidate_min_similarity", -1.0)
    with SessionLocal() as session:
        clear_database(session)
    batch, source_library = (tmp_path / name for name in ("batch", "source-library"))
    for directory in (batch, source_library):
        directory.mkdir()
    make_source(source_library / "old-source.png", "SALE")
    make_source(batch / "new-source.png", "NEW")

    with TestClient(app) as client:
        response = client.post("/api/v1/tasks/source-dedup", json={"source_batch_dir": str(batch), "source_library_dir": str(source_library), "idempotency_key": str(uuid.uuid4())})
    assert response.status_code == 202
    from app.workers.runner import claim_one_task, run_m1_scan

    with SessionLocal() as session:
        task = claim_one_task(session)
        assert task is not None
        run_m1_scan(task, session)
    assert (batch / "new-source.png").exists()
    with SessionLocal() as session:
        task = session.get(Task, int(response.json()["task_id"]))
        pairs = list(session.scalars(select(DuplicatePair).where(DuplicatePair.task_id == task.id)))
        roi_features = list(session.scalars(select(ImageFeature).where(ImageFeature.feature_scope == "SOURCE_PRINT")))
        assert task and task.status == "DONE"
        assert roi_features and all(feature.bbox_json and feature.bbox_json["method"] == "opencv-content-region-v1" for feature in roi_features)
        assert pairs and {pair.pair_type for pair in pairs} == {"SOURCE_SOURCE"}
        assert all(pair.machine_decision == "RETRIEVED_CANDIDATE" and pair.resolution_status == "CANDIDATE_RETAINED" for pair in pairs)
