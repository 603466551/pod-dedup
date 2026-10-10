import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete


@pytest.mark.skipif(not os.getenv("MYSQL_TEST_DATABASE_URL"), reason="需要隔离的MySQL测试库")
def test_created_task_can_be_cancelled_and_releases_its_lock(tmp_path) -> None:
    os.environ["DATABASE_URL"] = os.environ["MYSQL_TEST_DATABASE_URL"]
    from app.core.db import SessionLocal
    from app.main import app
    from app.models.tasks import Task, TaskEvent, TaskResourceLock

    with SessionLocal() as session:
        for model in (TaskResourceLock, TaskEvent, Task):
            session.execute(delete(model))
        task = Task(type="POD_CROP", status="CREATED", pod_library_dir=str(tmp_path), ratio_code="1x1", idempotency_key=str(uuid.uuid4()), settings_snapshot={}, counters={}, warnings=[])
        session.add(task)
        session.flush()
        session.add(TaskResourceLock(resource_key="POD_PRODUCTION:test", task_id=task.id))
        session.commit()
        task_id = task.id

    with TestClient(app) as client:
        response = client.post(f"/api/v1/tasks/{task_id}/cancel")

    assert response.status_code == 200
    assert response.json()["status"] == "CANCELLED"
    with SessionLocal() as session:
        assert session.get(Task, task_id).status == "CANCELLED"
        assert session.query(TaskResourceLock).filter_by(task_id=task_id).count() == 0
