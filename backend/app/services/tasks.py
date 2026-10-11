import hashlib
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.enums import TERMINAL_TASK_STATUSES, TaskStatus, TaskType
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
        # A POD dedup task eventually writes masters into the library.  Keep a
        # library-wide lease as well as the pending-folder lease, so a crop
        # cannot snapshot a partially archived batch.
        return [
            key("POD_PENDING", payload["pod_pending_dir"]),
            key("POD_LIBRARY", payload["pod_library_dir"]),
        ]
    if task_type == TaskType.POD_CROP:
        # Crops read the same POD masters that a dedup task writes.  The shared
        # POD_LIBRARY key makes those workflows mutually exclusive per library.
        return [
            key("POD_LIBRARY", payload["pod_library_dir"]),
            key(f"POD_PRODUCTION:{payload['ratio_code']}", payload["pod_library_dir"]),
        ]
    if task_type == TaskType.SOURCE_ORGANIZE:
        return [key("SOURCE_PROCESSED", payload["source_batch_dir"])]
    if task_type == TaskType.INDEX_REBUILD:
        return ["INDEX_REBUILD:global"]
    return [key("SOURCE_BATCH", payload["source_batch_dir"])]


def _same_pod_library(existing_path: str | None, requested_path: str) -> bool:
    """Compare stored POD-library paths defensively for pre-lock tasks too."""
    return bool(existing_path) and canonical_path(existing_path) == canonical_path(requested_path)


def _active_pod_library_task(session: Session, task_type: TaskType, payload: dict[str, Any]) -> Task | None:
    """Find an incompatible legacy task that has no shared POD_LIBRARY lock.

    The shared resource key protects newly created tasks.  This fallback also
    protects tasks created by an older application version before that key was
    introduced, until each of them reaches a terminal state.
    """
    if task_type not in {TaskType.POD_DEDUP, TaskType.POD_CROP}:
        return None
    terminal_statuses = [status.value for status in TERMINAL_TASK_STATUSES]
    active = session.scalars(
        select(Task).where(
            Task.type.in_((TaskType.POD_DEDUP.value, TaskType.POD_CROP.value)),
            Task.status.not_in(terminal_statuses),
        )
    )
    for existing in active:
        if _same_pod_library(existing.pod_library_dir, payload["pod_library_dir"]):
            return existing
    return None


def create_task(
    session: Session,
    task_type: TaskType,
    payload: dict[str, Any],
    warnings: list[str],
) -> Task:
    existing = get_by_idempotency_key(session, payload["idempotency_key"])
    if existing:
        return existing
    conflicting_task = _active_pod_library_task(session, task_type, payload)
    if conflicting_task is not None:
        raise TaskResourceBusyError("该历史POD图库正由未结束的去重或裁切任务使用，请等待其完成后再创建任务")
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
