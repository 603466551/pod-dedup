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


@pytest.mark.skipif(not os.getenv("MYSQL_TEST_DATABASE_URL"), reason="需要隔离的MySQL测试库")
def test_crop_is_blocked_until_same_library_dedup_is_terminal(tmp_path: Path) -> None:
    os.environ["DATABASE_URL"] = os.environ["MYSQL_TEST_DATABASE_URL"]
    from app.core.db import SessionLocal
    from app.main import app
    from app.models.tasks import Task

    pending, library = tmp_path / "pending", tmp_path / "library"
    pending.mkdir()
    library.mkdir()
    dedup_payload = {
        "pod_pending_dir": str(pending),
        "pod_library_dir": str(library),
        "dry_run": False,
        "idempotency_key": str(uuid.uuid4()),
    }
    crop_payload = {
        "pod_library_dir": str(library),
        "ratio_code": "1x1",
        "start_date": "20261011",
        "end_date": "20261011",
        "dry_run": False,
    }

    with TestClient(app) as client:
        dedup = client.post("/api/v1/tasks/pod-dedup", json=dedup_payload)
        blocked_crop = client.post("/api/v1/tasks/pod-crop", json={**crop_payload, "idempotency_key": str(uuid.uuid4())})
    assert dedup.status_code == 202
    assert blocked_crop.status_code == 409
    assert blocked_crop.json()["detail"]["code"] == "TASK_RESOURCE_BUSY"

    with SessionLocal() as session:
        task = session.get(Task, int(dedup.json()["task_id"]))
        task.status = "DONE"
        session.commit()

    with TestClient(app) as client:
        crop_after_dedup = client.post("/api/v1/tasks/pod-crop", json={**crop_payload, "idempotency_key": str(uuid.uuid4())})
    assert crop_after_dedup.status_code == 202
