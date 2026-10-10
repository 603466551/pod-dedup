import os
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.mark.skipif(not os.getenv("MYSQL_TEST_DATABASE_URL"), reason="需要隔离的MySQL测试库")
def test_same_pod_pending_directory_is_locked_until_task_is_terminal(tmp_path: Path) -> None:
    os.environ["DATABASE_URL"] = os.environ["MYSQL_TEST_DATABASE_URL"]
    from app.core.db import SessionLocal
    from app.main import app
    from app.models.tasks import Task

    batch, source_library, pending, library = (tmp_path / name for name in ("batch", "source", "pending", "library"))
    for directory in (batch, source_library, pending, library):
        directory.mkdir()
    payload = {"source_batch_dir": str(batch), "source_library_dir": str(source_library), "pod_pending_dir": str(pending), "pod_library_dir": str(library), "ratio_code": "3x4"}
    with TestClient(app) as client:
        first = client.post("/api/v1/tasks/pod-dedup", json={**payload, "idempotency_key": str(uuid.uuid4())})
        second = client.post("/api/v1/tasks/pod-dedup", json={**payload, "idempotency_key": str(uuid.uuid4())})
    assert first.status_code == 202
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "TASK_RESOURCE_BUSY"
    with SessionLocal() as session:
        task = session.get(Task, int(first.json()["task_id"]))
        task.status = "DONE"
        session.commit()
    with TestClient(app) as client:
        after_terminal = client.post("/api/v1/tasks/pod-dedup", json={**payload, "idempotency_key": str(uuid.uuid4())})
    assert after_terminal.status_code == 202
