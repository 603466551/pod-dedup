from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.app_logging import read_recent_runtime_logs
from app.core.db import get_session
from app.models.images import FileOperation, Review, TaskItem, VlmCall
from app.models.tasks import Task, TaskEvent
from app.services.task_time import worker_timestamp_for_display

router = APIRouter(prefix="/logs", tags=["logs"])


@router.get("/runtime")
def runtime_logs(lines: int = 100):
    lines = max(1, min(lines, 500))
    return {"items": read_recent_runtime_logs(lines), "retention_days": 14}


@router.get("/diagnostic")
def diagnostic_bundle(task_id: int | None = None, session: Session = Depends(get_session)):
    """Download a privacy-preserving diagnostic snapshot for support.

    It includes IDs, state transitions, error codes and application logs, but
    intentionally omits real filesystem paths, image names and credentials.
    """
    task_data = None
    if task_id is not None:
        task = session.get(Task, task_id)
        if task is None:
            raise HTTPException(404, detail={"code": "TASK_NOT_FOUND", "message": "任务不存在", "details": {}})
        task_data = {
            "id": task.id, "type": task.type, "status": task.status,
            "counters": task.counters, "warning_codes": [warning.split(":", 1)[0] for warning in task.warnings],
            "created_at": task.created_at.isoformat() if task.created_at else None,
            "started_at": worker_timestamp_for_display(task.started_at, task.settings_snapshot),
            "finished_at": worker_timestamp_for_display(task.finished_at, task.settings_snapshot),
        }
    item_statement = select(TaskItem)
    event_statement = select(TaskEvent)
    review_statement = select(Review)
    operation_statement = select(FileOperation)
    if task_id is not None:
        item_statement = item_statement.where(TaskItem.task_id == task_id)
        event_statement = event_statement.where(TaskEvent.task_id == task_id)
        review_statement = review_statement.where(Review.task_id == task_id)
        operation_statement = operation_statement.where(FileOperation.task_id == task_id)
    payload = {
        "format": "pod-dedup-diagnostic-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "task": task_data,
        "task_items": [{"id": item.id, "stage": item.stage, "status": item.status, "error_code": item.error_code} for item in session.scalars(item_statement.order_by(TaskItem.id.desc()).limit(300))],
        "task_events": [{"id": event.id, "level": event.level, "stage": event.stage, "created_at": event.created_at.isoformat() if event.created_at else None} for event in session.scalars(event_statement.order_by(TaskEvent.id.desc()).limit(300))],
        "reviews": [{"id": review.id, "status": review.status, "version": review.version, "duplicate_decision": review.duplicate_decision, "action_decision": review.action_decision} for review in session.scalars(review_statement.order_by(Review.id.desc()).limit(300))],
        "operations": [{"id": operation.id, "operation": operation.operation, "state": operation.state, "reason": operation.reason, "has_error": bool(operation.error_text)} for operation in session.scalars(operation_statement.order_by(FileOperation.id.desc()).limit(300))],
        "runtime_log": read_recent_runtime_logs(300),
    }
    filename = f"pod-dedup-diagnostic-task-{task_id}.json" if task_id is not None else "pod-dedup-diagnostic.json"
    return JSONResponse(payload, headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/task-events")
def task_events(task_id: int | None = None, page: int = 1, session: Session = Depends(get_session)):
    statement = select(TaskEvent).order_by(TaskEvent.id.desc())
    if task_id is not None:
        statement = statement.where(TaskEvent.task_id == task_id)
    rows = session.scalars(statement.offset((page - 1) * 50).limit(50))
    return {"items": [{"id": str(row.id), "task_id": str(row.task_id), "level": row.level, "stage": row.stage, "message": row.message, "created_at": row.created_at.isoformat() if row.created_at else None} for row in rows], "page": page}


@router.get("/vlm-calls")
def vlm_calls(task_id: int | None = None, page: int = 1, session: Session = Depends(get_session)):
    statement = select(VlmCall).order_by(VlmCall.id.desc())
    if task_id is not None:
        statement = statement.where(VlmCall.task_id == task_id)
    rows = session.scalars(statement.offset((page - 1) * 50).limit(50))
    return {"items": [{"id": str(row.id), "task_id": str(row.task_id), "pair_id": str(row.pair_id) if row.pair_id else None, "provider": row.provider, "model": row.model, "status": row.status, "error_code": row.error_code, "created_at": row.created_at.isoformat() if row.created_at else None} for row in rows], "page": page}
