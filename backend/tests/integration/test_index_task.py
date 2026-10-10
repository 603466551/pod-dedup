import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete


@pytest.mark.skipif(not os.getenv("MYSQL_TEST_DATABASE_URL"), reason="需要隔离的MySQL测试库")
def test_index_rebuild_is_a_persisted_worker_task() -> None:
    os.environ["DATABASE_URL"] = os.environ["MYSQL_TEST_DATABASE_URL"]
    from app.core.db import SessionLocal
    from app.main import app
    from app.models.images import DuplicatePair, FileOperation, Image, ImageFeature, ImageFile, Review, TaskItem, VlmCall
    from app.models.tasks import Task, TaskEvent, TaskResourceLock
    from app.workers.runner import claim_one_task, run_m1_scan

    with SessionLocal() as session:
        for model in (VlmCall, Review, DuplicatePair, FileOperation, ImageFeature, ImageFile, TaskItem, Image, TaskResourceLock, TaskEvent, Task):
            session.execute(delete(model))
        session.commit()
    with TestClient(app) as client:
        response = client.post("/api/v1/indexes/rebuild", json={"idempotency_key": str(uuid.uuid4())})
    assert response.status_code == 202 and response.json()["type"] == "INDEX_REBUILD"
    with SessionLocal() as session:
        task = claim_one_task(session)
        assert task is not None
        run_m1_scan(task, session)
        persisted = session.get(Task, task.id)
        assert persisted.status == "DONE"
        assert persisted.counters["indexes"] == {"SOURCE_FULL": 0, "SOURCE_PRINT": 0, "POD_FULL": 0}
