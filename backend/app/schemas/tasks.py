from typing import Literal
import re

from pydantic import BaseModel, Field


class SourceDedupRequest(BaseModel):
    source_batch_dir: str = Field(min_length=1)
    source_library_dir: str = Field(min_length=1)
    dry_run: bool = False
    idempotency_key: str = Field(min_length=8, max_length=80)


class SourceOrganizeRequest(BaseModel):
    source_batch_dir: str = Field(min_length=1)
    source_library_dir: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=8, max_length=80)


class PodDedupRequest(BaseModel):
    # MJ direct-POD batches have no source-image context.  Both source fields
    # are optional, but when one is supplied the other is required so the
    # optional source-organize step remains well-defined.
    source_batch_dir: str | None = None
    source_library_dir: str | None = None
    pod_pending_dir: str = Field(min_length=1)
    pod_library_dir: str = Field(min_length=1)
    dry_run: bool = False
    idempotency_key: str = Field(min_length=8, max_length=80)


class PodCropRequest(BaseModel):
    pod_library_dir: str = Field(min_length=1)
    ratio_code: str = Field(min_length=3, max_length=8)
    start_date: str = Field(pattern=r"^\d{8}$")
    end_date: str = Field(pattern=r"^\d{8}$")
    dry_run: bool = False
    idempotency_key: str = Field(min_length=8, max_length=80)


class ValidateTaskRequest(BaseModel):
    type: Literal["SOURCE_DEDUP", "SOURCE_ORGANIZE", "POD_DEDUP", "POD_CROP"]
    source_batch_dir: str | None = None
    source_library_dir: str | None = None
    pod_pending_dir: str | None = None
    pod_library_dir: str | None = None
    ratio_code: str | None = None
    start_date: str | None = None
    end_date: str | None = None


class TaskResponse(BaseModel):
    task_id: str
    type: str
    status: str
    warnings: list[str]
    counters: dict = Field(default_factory=dict)
    created_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


class TaskDetailResponse(TaskResponse):
    counters: dict
    archive_date: str | None
    errors: list[str]
