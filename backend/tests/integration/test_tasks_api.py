"""Requires an isolated MySQL 5.7+ database named with the `_test` suffix."""

import os
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.mark.skipif(not os.getenv("MYSQL_TEST_DATABASE_URL"), reason="需要隔离的MySQL测试库")
def test_task_is_idempotent_and_persists_for_new_api_client(tmp_path: Path) -> None:
    database_url = os.environ["MYSQL_TEST_DATABASE_URL"]
    assert "pod_dedup_test" in database_url, "测试只能使用隔离的 pod_dedup_test 数据库"
    os.environ["DATABASE_URL"] = database_url

    from app.main import app
    from app.core.db import SessionLocal
    from app.models.images import TaskItem

    batch = tmp_path / "source-batch"
    library = tmp_path / "source-library"
    for directory in (batch, library):
        directory.mkdir()
    request = {
        "source_batch_dir": str(batch),
        "source_library_dir": str(library),
        "dry_run": True,
        "idempotency_key": str(uuid.uuid4()),
    }

    with TestClient(app) as first_client:
        created = first_client.post("/api/v1/tasks/source-dedup", json=request)
        repeated = first_client.post("/api/v1/tasks/source-dedup", json=request)
    assert created.status_code == 202
    assert repeated.status_code == 202
    assert repeated.json()["task_id"] == created.json()["task_id"]
    task_id = int(created.json()["task_id"])
    processed_at = datetime.now()
    with SessionLocal() as session:
        session.add_all([
            TaskItem(task_id=task_id, observed_path="C:/safe/earlier.png", observed_path_digest=b"a" * 32,
                     stage="DECIDING", status="PASSED", updated_at=processed_at - timedelta(minutes=1)),
            TaskItem(task_id=task_id, observed_path="C:/safe/latest.png", observed_path_digest=b"b" * 32,
                     stage="DECIDING", status="CHECKING", updated_at=processed_at),
        ])
        session.commit()

    with TestClient(app) as restarted_client:
        response = restarted_client.get(f"/api/v1/tasks/{task_id}")
        progress = restarted_client.get(f"/api/v1/tasks/{task_id}/progress")
        events = restarted_client.get(f"/api/v1/logs/task-events?task_id={task_id}")
        vlm_calls = restarted_client.get(f"/api/v1/logs/vlm-calls?task_id={task_id}")
        diagnostic = restarted_client.get(f"/api/v1/logs/diagnostic?task_id={task_id}")
    assert response.status_code == 200
    assert response.json()["status"] == "CREATED"
    assert response.json()["created_at"] is not None
    assert progress.status_code == 200
    assert progress.json()["task"]["task_id"] == str(task_id)
    assert progress.json()["summary"] == {
        "total": 2,
        "processed": 1,
        "status_counts": {"CHECKING": 1, "PASSED": 1},
    }
    assert progress.json()["items"][0]["filename"] == "latest.png"
    assert progress.json()["items"][0]["updated_at"] is not None
    assert events.status_code == 200 and events.json()["items"]
    assert vlm_calls.status_code == 200 and isinstance(vlm_calls.json()["items"], list)
    assert diagnostic.status_code == 200
    assert diagnostic.json()["format"] == "pod-dedup-diagnostic-v1"
    assert diagnostic.json()["task"]["id"] == task_id
    assert "attachment;" in diagnostic.headers["content-disposition"]
