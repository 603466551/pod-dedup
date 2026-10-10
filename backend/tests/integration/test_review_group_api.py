import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select


@pytest.mark.skipif(not os.getenv("MYSQL_TEST_DATABASE_URL"), reason="需要隔离的MySQL测试库")
def test_pending_relations_are_grouped_and_resolved_together(tmp_path) -> None:
    os.environ["DATABASE_URL"] = os.environ["MYSQL_TEST_DATABASE_URL"]
    from app.core.db import SessionLocal
    from app.main import app
    from app.models.images import DuplicatePair, FileOperation, Image, ImageFeature, ImageFile, Review, TaskItem
    from app.models.tasks import Task, TaskEvent, TaskResourceLock

    with SessionLocal() as session:
        for model in (TaskResourceLock, Review, DuplicatePair, FileOperation, ImageFeature, ImageFile, TaskItem, Image, TaskEvent, Task):
            session.execute(delete(model))
        task = Task(type="POD_DEDUP", status="WAIT_REVIEW", pod_library_dir=str(tmp_path), idempotency_key=str(uuid.uuid4()), settings_snapshot={}, counters={}, warnings=[])
        session.add(task)
        session.flush()
        images = [Image(kind="POD", original_filename=f"image-{index}.png", status="PENDING") for index in range(3)]
        session.add_all(images)
        session.flush()
        for new_index, match_index in ((0, 1), (1, 0), (1, 2), (2, 1)):
            pair = DuplicatePair(task_id=task.id, image_new_id=images[new_index].id, image_match_id=images[match_index].id, pair_type="POD_POD", machine_decision="RETRIEVED_CANDIDATE", rule_id="TEST", evidence_json={"cosine_similarity": 0.9}, review_required=True, resolution_status="PENDING")
            session.add(pair)
            session.flush()
            session.add(Review(pair_id=pair.id, task_id=task.id, status="PENDING", version=1))
        session.commit()

    with TestClient(app) as client:
        groups = client.get("/api/v1/reviews/groups")
        assert groups.status_code == 200
        payload = groups.json()
        assert payload["pending_review_count"] == 4
        assert len(payload["items"]) == 1
        group = payload["items"][0]
        assert len(group["images"]) == 3
        result = client.post(f"/api/v1/reviews/{group['seed_review_id']}/group-decision", json={
            "decision": "DUPLICATE_KEEP_ALL",
            "versions": {relation["review_id"]: relation["version"] for relation in group["relations"]},
        })
    assert result.status_code == 200
    with SessionLocal() as session:
        assert list(session.scalars(select(Review.status).order_by(Review.id))) == ["RESOLVED"] * 4
