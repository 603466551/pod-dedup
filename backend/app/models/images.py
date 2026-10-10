from datetime import date, datetime
from typing import Any

from sqlalchemy import BINARY, JSON, BigInteger, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Image(Base):
    __tablename__ = "images"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(12), nullable=False, index=True)
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    sha256: Mapped[bytes | None] = mapped_column(BINARY(32))
    pixel_digest: Mapped[bytes | None] = mapped_column(BINARY(32))
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    file_size: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="PENDING")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class ImageFile(Base):
    __tablename__ = "image_files"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    image_id: Mapped[int] = mapped_column(ForeignKey("images.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_path_digest: Mapped[bytes] = mapped_column(BINARY(32), nullable=False, unique=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mtime_ns: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[bytes] = mapped_column(BINARY(32), nullable=False)
    file_status: Mapped[str] = mapped_column(String(20), nullable=False, default="PRESENT")
    archive_date: Mapped[date | None] = mapped_column(Date)
    ratio_code: Mapped[str | None] = mapped_column(String(8))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class TaskItem(Base):
    __tablename__ = "task_items"
    __table_args__ = (UniqueConstraint("task_id", "observed_path_digest", name="uq_task_item_path"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), nullable=False, index=True)
    image_id: Mapped[int | None] = mapped_column(ForeignKey("images.id"))
    observed_path: Mapped[str] = mapped_column(Text, nullable=False)
    observed_path_digest: Mapped[bytes] = mapped_column(BINARY(32), nullable=False)
    stage: Mapped[str] = mapped_column(String(30), nullable=False, default="PENDING")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="PENDING")
    error_code: Mapped[str | None] = mapped_column(String(50))
    error_message: Mapped[str | None] = mapped_column(Text)
    snapshot_sha256: Mapped[bytes | None] = mapped_column(BINARY(32))
    snapshot_size: Mapped[int | None] = mapped_column(BigInteger)
    snapshot_mtime_ns: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class FileOperation(Base):
    __tablename__ = "file_operations"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"), index=True)
    task_item_id: Mapped[int | None] = mapped_column(ForeignKey("task_items.id"), index=True)
    image_id: Mapped[int | None] = mapped_column(ForeignKey("images.id"), index=True)
    operation: Mapped[str] = mapped_column(String(16), nullable=False)
    origin_path: Mapped[str | None] = mapped_column(Text)
    target_path: Mapped[str | None] = mapped_column(Text)
    origin_sha256: Mapped[bytes] = mapped_column(BINARY(32), nullable=False)
    expected_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    operation_key: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="PREPARED")
    reason: Mapped[str] = mapped_column(String(80), nullable=False)
    thumbnail_path: Mapped[str | None] = mapped_column(Text)
    error_text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class DuplicatePair(Base):
    __tablename__ = "duplicate_pairs"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), nullable=False, index=True)
    image_new_id: Mapped[int] = mapped_column(ForeignKey("images.id"), nullable=False)
    image_match_id: Mapped[int | None] = mapped_column(ForeignKey("images.id"))
    pair_type: Mapped[str] = mapped_column(String(20), nullable=False)
    machine_decision: Mapped[str] = mapped_column(String(32), nullable=False)
    rule_id: Mapped[str] = mapped_column(String(80), nullable=False)
    evidence_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    review_required: Mapped[bool] = mapped_column(default=False, nullable=False)
    resolution_status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Review(Base):
    __tablename__ = "reviews"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    pair_id: Mapped[int] = mapped_column(ForeignKey("duplicate_pairs.id"), nullable=False, unique=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    duplicate_decision: Mapped[str | None] = mapped_column(String(24))
    action_decision: Mapped[str | None] = mapped_column(String(28))
    note: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class ImageFeature(Base):
    __tablename__ = "image_features"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    image_id: Mapped[int] = mapped_column(ForeignKey("images.id"), nullable=False, index=True)
    feature_scope: Mapped[str] = mapped_column(String(28), nullable=False)
    region_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    bbox_json: Mapped[dict | None] = mapped_column(JSON)
    model_id: Mapped[str] = mapped_column(String(128), nullable=False)
    model_revision: Mapped[str] = mapped_column(String(128), nullable=False)
    preprocess_version: Mapped[str] = mapped_column(String(64), nullable=False)
    dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    vector_blob: Mapped[bytes] = mapped_column(nullable=False)
    vector_sha256: Mapped[bytes] = mapped_column(BINARY(32), nullable=False)
    faiss_vector_id: Mapped[int | None] = mapped_column(BigInteger)
    is_valid: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class VlmCall(Base):
    __tablename__ = "vlm_calls"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), nullable=False, index=True)
    pair_id: Mapped[int | None] = mapped_column(ForeignKey("duplicate_pairs.id"))
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    request_metadata: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    response_json: Mapped[dict | None] = mapped_column(JSON)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
