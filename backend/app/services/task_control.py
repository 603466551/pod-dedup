"""Cooperative task cancellation at safe per-image checkpoints."""

from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.enums import TaskStatus
from app.models.tasks import Task, TaskResourceLock
from app.repositories.tasks import add_event


def cancellation_requested(session: Session, task_id: int) -> bool:
    status = session.scalar(select(Task.status).where(Task.id == task_id))
    return status in {TaskStatus.CANCEL_REQUESTED.value, TaskStatus.CANCELLED.value}


def stop_if_cancelled(session: Session, task: Task) -> bool:
    """Finish a requested cancellation only between persisted file operations."""
    status = session.scalar(select(Task.status).where(Task.id == task.id))
    if status == TaskStatus.CANCELLED.value:
        return True
    if status != TaskStatus.CANCEL_REQUESTED.value:
        return False
    session.refresh(task)
    task.status = TaskStatus.CANCELLED.value
    task.lease_until = None
    task.finished_at = datetime.now(UTC).replace(tzinfo=None)
    add_event(session, task, "WARNING", TaskStatus.CANCELLED.value, "任务已取消；已完成的文件操作保持不回滚")
    session.execute(delete(TaskResourceLock).where(TaskResourceLock.task_id == task.id))
    session.commit()
    return True
