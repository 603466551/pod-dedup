from fastapi import APIRouter, Depends, HTTPException, status
from collections import Counter
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_session
from app.core.enums import TERMINAL_TASK_STATUSES, TaskStatus, TaskType
from app.repositories.tasks import add_event, get_task, list_tasks
from app.models.images import TaskItem
from app.models.tasks import TaskEvent
from app.schemas.tasks import (
    PodDedupRequest,
    PodCropRequest,
    SourceDedupRequest,
    SourceOrganizeRequest,
    TaskDetailResponse,
    TaskResponse,
    ValidateTaskRequest,
)
from app.services.tasks import TaskResourceBusyError, create_task
from app.services.task_control import stop_if_cancelled
from app.services.task_time import worker_timestamp_for_display
from app.storage.paths import PathValidationError, canonical_path, validate_pod_paths, validate_source_batch
from app.services.ratios import normalize_ratio

router = APIRouter(prefix="/tasks", tags=["tasks"])

IN_PROGRESS_ITEM_STATUSES = {"PENDING", "FROZEN", "CHECKING", "MOVING"}


def task_response(task) -> TaskResponse:
    return TaskResponse(
        task_id=str(task.id), type=task.type, status=task.status, warnings=task.warnings,
        counters=task.counters,
        created_at=task.created_at.isoformat() if task.created_at else None,
        started_at=worker_timestamp_for_display(task.started_at, task.settings_snapshot),
        finished_at=worker_timestamp_for_display(task.finished_at, task.settings_snapshot),
    )


def validate_payload(payload: ValidateTaskRequest) -> list[str]:
    warnings: list[str] = []
    try:
        source_values = (payload.source_batch_dir, payload.source_library_dir)
        if any(source_values) and not all(source_values):
            raise PathValidationError("来源整理必须同时提供本次来源文件夹和历史源图库")
        if payload.source_batch_dir and payload.source_library_dir:
            warnings.extend(validate_source_batch(payload.source_batch_dir, payload.source_library_dir))
        if payload.type == TaskType.POD_DEDUP.value:
            if not payload.pod_pending_dir or not payload.pod_library_dir:
                raise PathValidationError("POD任务必须提供待处理目录和POD图库")
            warnings.extend(validate_pod_paths(payload.pod_pending_dir, payload.pod_library_dir))
        if payload.type == TaskType.POD_CROP.value:
            if not payload.pod_library_dir:
                raise PathValidationError("POD裁切任务必须提供历史POD图库")
            if not canonical_path(payload.pod_library_dir).is_dir():
                raise PathValidationError("历史POD图库当前不可访问")
            if not payload.ratio_code:
                raise PathValidationError("POD裁切任务必须提供输出比例")
            normalize_ratio(payload.ratio_code)
            if not payload.start_date or not payload.end_date or payload.start_date > payload.end_date:
                raise PathValidationError("时间范围必须是有效且顺序正确的 YYYYMMDD 日期")
            try:
                datetime.strptime(payload.start_date, "%Y%m%d")
                datetime.strptime(payload.end_date, "%Y%m%d")
            except ValueError as error:
                raise PathValidationError("时间范围必须是有效且顺序正确的 YYYYMMDD 日期") from error
    except PathValidationError as error:
        raise HTTPException(status_code=422, detail={"code": "PATH_RISK", "message": str(error), "details": {}}) from error
    return warnings


@router.post("/validate")
def validate_task(payload: ValidateTaskRequest):
    warnings = validate_payload(payload)
    return {"ok": True, "errors": [], "warnings": warnings, "scanned_preview_count": 0}


def create(payload: dict, task_type: TaskType, session: Session, warnings: list[str]):
    try:
        task = create_task(session, task_type, payload, warnings)
    except TaskResourceBusyError as error:
        raise HTTPException(status_code=409, detail={"code": "TASK_RESOURCE_BUSY", "message": str(error), "details": {}}) from error
    return task_response(task)


@router.post("/source-dedup", response_model=TaskResponse, status_code=status.HTTP_202_ACCEPTED)
def create_source_dedup(payload: SourceDedupRequest, session: Session = Depends(get_session)):
    warnings = validate_payload(ValidateTaskRequest(type="SOURCE_DEDUP", **payload.model_dump()))
    return create(payload.model_dump(), TaskType.SOURCE_DEDUP, session, warnings)


@router.post("/source-organize", response_model=TaskResponse, status_code=status.HTTP_202_ACCEPTED)
def create_source_organize(payload: SourceOrganizeRequest, session: Session = Depends(get_session)):
    warnings = validate_payload(ValidateTaskRequest(type="SOURCE_ORGANIZE", **payload.model_dump()))
    return create(payload.model_dump(), TaskType.SOURCE_ORGANIZE, session, warnings)


@router.post("/pod-dedup", response_model=TaskResponse, status_code=status.HTTP_202_ACCEPTED)
def create_pod_dedup(payload: PodDedupRequest, session: Session = Depends(get_session)):
    warnings = validate_payload(ValidateTaskRequest(type="POD_DEDUP", **payload.model_dump()))
    return create(payload.model_dump(), TaskType.POD_DEDUP, session, warnings)


@router.post("/pod-crop", response_model=TaskResponse, status_code=status.HTTP_202_ACCEPTED)
def create_pod_crop(payload: PodCropRequest, session: Session = Depends(get_session)):
    data = payload.model_dump()
    data["ratio_code"] = normalize_ratio(data["ratio_code"])
    warnings = validate_payload(ValidateTaskRequest(type="POD_CROP", **data))
    return create(data, TaskType.POD_CROP, session, warnings)


@router.get("")
def get_tasks(type: str | None = None, status: str | None = None, page: int = 1, session: Session = Depends(get_session)):
    return {"items": [task_response(task).model_dump() for task in list_tasks(session, type, status, page)], "page": page}


@router.get("/{task_id}", response_model=TaskDetailResponse)
def get_task_detail(task_id: int, session: Session = Depends(get_session)):
    task = get_task(session, task_id)
    if not task:
        raise HTTPException(status_code=404, detail={"code": "TASK_NOT_FOUND", "message": "任务不存在", "details": {}})
    return TaskDetailResponse(
        **task_response(task).model_dump(),
        archive_date=task.archive_date.isoformat() if task.archive_date else None,
        errors=[],
    )


@router.post("/{task_id}/cancel", response_model=TaskResponse)
def cancel_task(task_id: int, session: Session = Depends(get_session)):
    task = get_task(session, task_id)
    if not task:
        raise HTTPException(status_code=404, detail={"code": "TASK_NOT_FOUND", "message": "任务不存在", "details": {}})
    if task.status in {status.value for status in TERMINAL_TASK_STATUSES}:
        raise HTTPException(status_code=409, detail={"code": "TASK_ALREADY_FINISHED", "message": "任务已结束，无法取消", "details": {"status": task.status}})
    if task.status == TaskStatus.CANCEL_REQUESTED.value:
        return task_response(task)
    previous_status = task.status
    task.status = TaskStatus.CANCEL_REQUESTED.value
    add_event(session, task, "WARNING", TaskStatus.CANCEL_REQUESTED.value, "已请求取消；当前单图操作完成后将停止")
    session.commit()
    # CREATED and WAIT_REVIEW have no Worker-owned file operation in progress,
    # so they can become terminal immediately and release their directory lock.
    if previous_status in {TaskStatus.CREATED.value, TaskStatus.WAIT_REVIEW.value, TaskStatus.PAUSED.value}:
        stop_if_cancelled(session, task)
    return task_response(task)


@router.get("/{task_id}/progress")
def get_task_progress(task_id: int, session: Session = Depends(get_session)):
    """A compact, polling-friendly task view without exposing real paths."""
    task = get_task(session, task_id)
    if not task:
        raise HTTPException(status_code=404, detail={"code": "TASK_NOT_FOUND", "message": "任务不存在", "details": {}})
    # Task items are created while the manifest is frozen (normally filename
    # order).  The progress view must instead surface the items most recently
    # handled by the worker.
    items = list(session.scalars(
        select(TaskItem)
        .where(TaskItem.task_id == task_id)
        .order_by(TaskItem.updated_at.desc(), TaskItem.id.desc())
    ))
    events = list(session.scalars(select(TaskEvent).where(TaskEvent.task_id == task_id).order_by(TaskEvent.id.desc()).limit(100)))
    status_counts = Counter(item.status for item in items)
    processed_count = sum(item.status not in IN_PROGRESS_ITEM_STATUSES for item in items)
    return {
        "task": task_response(task).model_dump(),
        "summary": {
            "total": len(items),
            "processed": processed_count,
            "status_counts": dict(status_counts),
        },
        "items": [
            {
                "id": str(item.id), "filename": item.observed_path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1],
                "stage": item.stage, "status": item.status,
                "error_code": item.error_code,
                "updated_at": item.updated_at.isoformat() if item.updated_at else None,
            }
            for item in items
        ],
        "events": [
            {"id": str(event.id), "level": event.level, "stage": event.stage,
             "message": event.message,
             "created_at": event.created_at.isoformat() if event.created_at else None}
            for event in reversed(events)
        ],
    }


@router.get("/{task_id}/items")
def get_task_items(task_id: int, page: int = 1, session: Session = Depends(get_session)):
    if not get_task(session, task_id):
        raise HTTPException(status_code=404, detail={"code": "TASK_NOT_FOUND", "message": "任务不存在", "details": {}})
    items = session.scalars(select(TaskItem).where(TaskItem.task_id == task_id).order_by(TaskItem.id).offset((page - 1) * 50).limit(50))
    return {"items": [{"id": str(item.id), "path": item.observed_path, "stage": item.stage, "status": item.status, "error_code": item.error_code, "error_message": item.error_message} for item in items], "page": page}
