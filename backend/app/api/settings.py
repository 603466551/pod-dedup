from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.db import get_session
from app.services.settings import public, update

router = APIRouter(prefix="/settings", tags=["settings"])


class SettingsUpdate(BaseModel):
    source_library_dir: str | None = None
    pod_library_dir: str | None = None
    pod_pending_dir: str | None = None
    source_library_locked: bool | None = None
    pod_library_locked: bool | None = None
    retrieval_top_k: int | None = Field(default=None, ge=1, le=100)
    retrieval_candidate_min_similarity: float | None = Field(default=None, ge=-1, le=1)
    source_visual_auto_delete: bool | None = None
    pod_visual_auto_delete: bool | None = None
    source_visual_rule_validated: bool | None = None
    app_timezone: str | None = Field(default=None, max_length=64)
    ratio_rel_tolerance: float | None = Field(default=None, ge=0, le=0.2)
    vlm_enabled: bool | None = None
    vlm_base_url: str | None = None
    vlm_model: str | None = None
    vlm_api_key: str | None = None
    vlm_max_calls_per_task: int | None = Field(default=None, ge=0, le=10000)
    production_ratio_codes: list[str] | None = None


@router.get("")
def get_settings(session: Session = Depends(get_session)):
    return public(session)


@router.put("")
def put_settings(payload: SettingsUpdate, session: Session = Depends(get_session)):
    values = payload.model_dump(exclude_unset=True)
    for key in ("source_library_dir", "pod_library_dir", "pod_pending_dir"):
        if value := values.get(key):
            if not Path(value).is_absolute():
                raise HTTPException(422, detail={"code": "PATH_NOT_ABSOLUTE", "message": f"{key}必须是绝对路径", "details": {}})
    try:
        return update(session, values)
    except ValueError as error:
        raise HTTPException(422, detail={"code": "INVALID_SETTING", "message": str(error), "details": {}}) from error
