import hashlib
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.enums import TaskStatus, TaskType
from app.models.tasks import Task, TaskResourceLock
from app.repositories.tasks import add_event, get_by_idempotency_key
from app.storage.paths import canonical_path
from app.core.config import settings
from app.services.settings import effective


class TaskResourceBusyError(ValueError):
    pass


def _resource_keys(task_type: TaskType, payload: dict[str, Any]) -> list[str]:
    def key(prefix: str, value: str) -> str:
        canonical = canonical_path(value).as_posix().casefold().encode("utf-8")
        return f"{prefix}:{hashlib.sha256(canonical).hexdigest()}"
    if task_type == TaskType.POD_DEDUP:
        return [key("POD_PENDING", payload["pod_pending_dir"])]
    if task_type == TaskType.POD_CROP:
        return [key(f"POD_PRODUCTION:{payload['ratio_code']}", payload["pod_library_dir"])]
    if task_type == TaskType.SOURCE_ORGANIZE:
        return [key("SOURCE_PROCESSED", payload["source_batch_dir"])]
    if task_type == TaskType.INDEX_REBUILD:
        return ["INDEX_REBUILD:global"]
    return [key("SOURCE_BATCH", payload["source_batch_dir"])]


def create_task(
    session: Session,
    task_type: TaskType,
    payload: dict[str, Any],
    warnings: list[str],
) -> Task:
    existing = get_by_idempotency_key(session, payload["idempotency_key"])
    if existing:
        return existing
    # Terminal tasks no longer own their directories.  WAIT_REVIEW remains
    # intentionally locked so a later batch cannot be mixed into it.
    terminal_ids = select(Task.id).where(Task.status.in_([status.value for status in {TaskStatus.DONE, TaskStatus.PARTIAL_COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}]))
    session.execute(delete(TaskResourceLock).where(TaskResourceLock.task_id.in_(terminal_ids)))
    resource_keys = _resource_keys(task_type, payload)
    occupied = session.scalar(select(TaskResourceLock).where(TaskResourceLock.resource_key.in_(resource_keys)))
    if occupied:
        raise TaskResourceBusyError("该目录正被未结案任务接管，请等待任务结束或完成审核")
    task_settings = effective(session)
    task_settings.pop("vlm_api_key", None)
    task = Task(
        type=task_type.value,
        status=TaskStatus.CREATED.value,
        source_batch_dir=payload.get("source_batch_dir"),
        source_library_dir=payload.get("source_library_dir"),
        pod_pending_dir=payload.get("pod_pending_dir"),
        pod_library_dir=payload.get("pod_library_dir"),
        ratio_code=payload.get("ratio_code"),
        idempotency_key=payload["idempotency_key"],
        settings_snapshot={
            **task_settings,
            "dry_run": payload.get("dry_run", False),
            "crop_start_date": payload.get("start_date"),
            "crop_end_date": payload.get("end_date"),
        },
        counters={"scanned": 0, "processed": 0, "errors": 0},
        warnings=warnings,
    )
    session.add(task)
    session.flush()
    for resource_key in resource_keys:
        session.add(TaskResourceLock(resource_key=resource_key, task_id=task.id))
    add_event(session, task, "INFO", TaskStatus.CREATED.value, "任务已创建，等待Worker领取")
    session.commit()
    session.refresh(task)
    return task
