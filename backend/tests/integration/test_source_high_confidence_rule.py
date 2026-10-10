import os
import uuid
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from sqlalchemy import delete


def patterned_image(path: Path, jpeg: bool = False) -> None:
    rng = np.random.default_rng(42)
    values = rng.integers(0, 255, (300, 240, 3), dtype=np.uint8)
    Image.fromarray(values).save(path, quality=85) if jpeg else Image.fromarray(values).save(path)


@pytest.mark.skipif(not os.getenv("MYSQL_TEST_DATABASE_URL"), reason="需要隔离的MySQL测试库")
def test_explicit_high_confidence_source_rule_deletes_only_with_all_evidence(tmp_path: Path, monkeypatch) -> None:
    os.environ["DATABASE_URL"] = os.environ["MYSQL_TEST_DATABASE_URL"]
    from app.core.config import settings
    from app.core.db import SessionLocal
    from app.dedup.source.roi import PrintRegion
    from app.models.images import DuplicatePair, FileOperation, Image as ImageModel, ImageFeature, ImageFile, Review, TaskItem, VlmCall
    from app.models.tasks import Task, TaskEvent, TaskResourceLock
    from app.services.source_dedup import deduplicate
    from app.vlm.client import ComparisonResult

    with SessionLocal() as session:
        for model in (VlmCall, Review, DuplicatePair, FileOperation, ImageFeature, ImageFile, TaskItem, ImageModel, TaskResourceLock, TaskEvent, Task):
            session.execute(delete(model))
        session.commit()
    batch, source_library, pod_library = (tmp_path / name for name in ("batch", "source", "pod"))
    for directory in (batch, source_library, pod_library): directory.mkdir()
    patterned_image(source_library / "old.png")
    candidate = batch / "new.jpg"
    patterned_image(candidate, jpeg=True)
    region = PrintRegion(0, 0, 240, 300, 0.9)
    monkeypatch.setattr(settings, "retrieval_candidate_min_similarity", -1.0)
    monkeypatch.setattr("app.indexing.catalog.locate_print_region", lambda _path: region)
    monkeypatch.setattr("app.services.source_dedup.locate_print_region", lambda _path: region)
    monkeypatch.setattr("app.services.source_dedup.compare", lambda *_args, **_kwargs: ComparisonResult("same", True, 0.99, False, "none", "same print"))
    monkeypatch.setattr("app.services.source_dedup.verify_print_correspondence", lambda *_args: {"valid": True, "good_matches": 30, "inliers": 25, "inlier_ratio": 0.83, "method": "orb-ransac-v1"})
    with SessionLocal() as session:
        task = Task(type="SOURCE_DEDUP", status="SCANNING", source_batch_dir=str(batch), source_library_dir=str(source_library), pod_library_dir=str(pod_library), idempotency_key=str(uuid.uuid4()), settings_snapshot={"source_visual_auto_delete": True, "source_visual_rule_validated": True, "retrieval_candidate_min_similarity": -1.0}, counters={}, warnings=[])
        session.add(task); session.commit()
        deduplicate(task, session, tmp_path / "thumbs")
        pairs = session.query(DuplicatePair).filter(DuplicatePair.task_id == task.id).all()
        assert any(pair.machine_decision == "SOURCE_VISUAL_HIGH_CONFIRMED" and pair.resolution_status == "AUTO_DELETED" for pair in pairs), [(pair.machine_decision, pair.evidence_json) for pair in pairs]
        assert session.query(FileOperation).filter(FileOperation.reason == "SOURCE_VISUAL_HIGH_CONFIRMED").count() == 1
    assert not candidate.exists()
