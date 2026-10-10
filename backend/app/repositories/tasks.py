import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.app_logging import configure_runtime_logging
from app.models.tasks import Task, TaskEvent


def get_by_idempotency_key(session: Session, key: str) -> Task | None:
    return session.scalar(select(Task).where(Task.idempotency_key == key))


def get_task(session: Session, task_id: int) -> Task | None:
    return session.get(Task, task_id)


def list_tasks(session: Session, task_type: str | None, status: str | None, page: int) -> list[Task]:
    statement = select(Task).order_by(Task.id.desc()).offset((page - 1) * 50).limit(50)
    if task_type:
        statement = statement.where(Task.type == task_type)
    if status:
        statement = statement.where(Task.status == status)
    return list(session.scalars(statement))


def add_event(session: Session, task: Task, level: str, stage: str, message: str) -> None:
    session.add(TaskEvent(task_id=task.id, level=level, stage=stage, message=message, details_json={}))
    # The database event has the user-visible detail.  The rotating runtime log
    # intentionally records only stable identifiers, never a user image path.
    logger = configure_runtime_logging().getChild("events")
    logger.log(getattr(logging, level.upper(), logging.INFO), "task_id=%s stage=%s", task.id, stage)

