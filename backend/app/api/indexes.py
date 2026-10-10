import uuid

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.db import get_session
from app.core.enums import TaskType
from app.schemas.tasks import TaskResponse
from app.services.tasks import TaskResourceBusyError, create_task

router = APIRouter(prefix="/indexes", tags=["indexes"])


class IndexRequest(BaseModel):
    idempotency_key: str = Field(default_factory=lambda: str(uuid.uuid4()), min_length=8, max_length=80)


def _enqueue(payload: IndexRequest, session: Session) -> TaskResponse:
    try:
        task = create_task(session, TaskType.INDEX_REBUILD, payload.model_dump(), [])
    except TaskResourceBusyError as error:
        from fastapi import HTTPException
        raise HTTPException(409, detail={"code": "TASK_RESOURCE_BUSY", "message": str(error), "details": {}}) from error
    return TaskResponse(task_id=str(task.id), type=task.type, status=task.status, warnings=task.warnings)


@router.post("/rebuild", response_model=TaskResponse, status_code=status.HTTP_202_ACCEPTED)
def rebuild_pod_index(payload: IndexRequest, session: Session = Depends(get_session)):
    return _enqueue(payload, session)


@router.post("/reconcile", response_model=TaskResponse, status_code=status.HTTP_202_ACCEPTED)
def reconcile_indexes(payload: IndexRequest, session: Session = Depends(get_session)):
    return _enqueue(payload, session)
