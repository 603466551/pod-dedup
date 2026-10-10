from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_session
from app.models.images import FileOperation

router = APIRouter(prefix="/operations", tags=["operations"])


@router.get("")
def list_operations(task_id: int | None = None, page: int = 1, session: Session = Depends(get_session)):
    statement = select(FileOperation).order_by(FileOperation.id.desc())
    if task_id is not None:
        statement = statement.where(FileOperation.task_id == task_id)
    rows = session.scalars(statement.offset((page - 1) * 50).limit(50))
    return {"items": [{"id": str(op.id), "task_id": str(op.task_id) if op.task_id else None, "operation": op.operation, "origin_path": op.origin_path, "target_path": op.target_path, "state": op.state, "reason": op.reason, "thumbnail_path": op.thumbnail_path, "error": op.error_text} for op in rows], "page": page}
