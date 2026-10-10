import os
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete


@pytest.mark.skipif(not os.getenv("MYSQL_TEST_DATABASE_URL"), reason="需要隔离的MySQL测试库")
def test_settings_hide_secret_and_freeze_new_task_snapshot(tmp_path: Path) -> None:
    os.environ["DATABASE_URL"] = os.environ["MYSQL_TEST_DATABASE_URL"]
    from app.core.db import SessionLocal
    from app.main import app
    from app.models.tasks import AppSetting, Task

    batch, source_library, pod_library = (tmp_path / name for name in ("batch", "source", "pod"))
    for directory in (batch, source_library, pod_library):
        directory.mkdir()
    with SessionLocal() as session:
        session.execute(delete(AppSetting))
        session.commit()
    with TestClient(app) as client:
        blocked = client.put("/api/v1/settings", json={"source_visual_auto_delete": True})
        enabled = client.put("/api/v1/settings", json={"source_visual_rule_validated": True, "source_visual_auto_delete": True})
        invalid_timezone = client.put("/api/v1/settings", json={"app_timezone": "not/a-timezone"})
        null_timezone = client.put("/api/v1/settings", json={"app_timezone": None})
        saved = client.put("/api/v1/settings", json={"retrieval_top_k": 7, "retrieval_candidate_min_similarity": 0.73, "app_timezone": "UTC", "ratio_rel_tolerance": 0.03, "vlm_max_calls_per_task": 12, "vlm_api_key": "test-secret", "vlm_model": "test-model", "source_library_dir": str(source_library), "pod_library_dir": str(pod_library), "source_library_locked": True, "pod_library_locked": True})
        read = client.get("/api/v1/settings")
        created = client.post("/api/v1/tasks/source-dedup", json={"source_batch_dir": str(batch), "source_library_dir": str(source_library), "pod_library_dir": str(pod_library), "idempotency_key": str(uuid.uuid4())})
    assert blocked.status_code == 422
    assert enabled.status_code == 200
    assert invalid_timezone.status_code == 422
    assert null_timezone.status_code == 422
    assert saved.status_code == 200 and read.status_code == 200 and created.status_code == 202
    assert saved.json()["vlm_api_key"] == "***已配置***"
    assert "test-secret" not in str(read.json())
    assert read.json()["source_library_dir"] == str(source_library)
    assert read.json()["pod_library_dir"] == str(pod_library)
    assert read.json()["source_library_locked"] is True
    assert read.json()["pod_library_locked"] is True
    assert read.json()["source_visual_rule_validated"] is True
    assert read.json()["source_visual_auto_delete"] is True
    with SessionLocal() as session:
        task = session.get(Task, int(created.json()["task_id"]))
        assert task.settings_snapshot["retrieval_top_k"] == 7
        assert task.settings_snapshot["retrieval_candidate_min_similarity"] == 0.73
        assert task.settings_snapshot["source_visual_rule_validated"] is True
        assert task.settings_snapshot["source_visual_auto_delete"] is True
        assert task.settings_snapshot["app_timezone"] == "UTC"
        assert task.settings_snapshot["ratio_rel_tolerance"] == 0.03
        assert task.settings_snapshot["vlm_max_calls_per_task"] == 12
        assert "vlm_api_key" not in task.settings_snapshot
        session.execute(delete(AppSetting))
        session.commit()
