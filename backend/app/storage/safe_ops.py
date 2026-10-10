"""The only M2 module permitted to change user image files."""

import os
import shutil
import uuid
from math import gcd
from datetime import datetime
from pathlib import Path

from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.images import FileOperation

from app.storage.fingerprint import Fingerprint, fingerprint, verify_snapshot


class FileChangedError(RuntimeError):
    pass


def timestamped_filename(source: Path, now: datetime | None = None) -> str:
    """Create the canonical library filename while preserving its extension.

    The caller persists the planned target before changing a file.  Therefore a
    retry never calls this function for an already-planned operation, even when
    it crosses a millisecond or a process restart.
    """
    moment = now or datetime.now()
    return f"{moment:%Y%m%d%H%M%S}{moment.microsecond // 1000:03d}{source.suffix}"


def unique_target(directory: Path, name: str, expected_sha256: bytes | None = None) -> Path:
    candidate = directory / name
    stem, suffix = candidate.stem, candidate.suffix
    index = 0
    while candidate.exists():
        if expected_sha256 and fingerprint(candidate).sha256 == expected_sha256:
            return candidate
        index += 1
        candidate = directory / f"{stem}_{index}{suffix}"
    return candidate


def plan_target(directory: Path, name: str, expected_sha256: bytes | None = None) -> Path:
    """Choose a collision-safe target before persisting an operation intent."""
    return unique_target(directory, name, expected_sha256)


def _planned_target(destination_dir: Path, target: Path | None, name: str, expected_sha256: bytes) -> Path:
    if target is None:
        return plan_target(destination_dir, name, expected_sha256)
    destination = destination_dir.resolve(strict=False)
    planned = target.resolve(strict=False)
    if planned.parent != destination:
        raise ValueError("预定目标路径不属于指定目标目录")
    return planned


def thumbnail(source: Path, target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as image:
        image.thumbnail((360, 360))
        image.convert("RGB").save(target, format="JPEG", quality=85)
    return target


def move_verified(source: Path, destination_dir: Path, snapshot: Fingerprint, *, target: Path | None = None) -> Path:
    if not verify_snapshot(source, snapshot):
        raise FileChangedError("文件在操作前已变更，拒绝移动")
    destination_dir.mkdir(parents=True, exist_ok=True)
    planned = _planned_target(destination_dir, target, source.name, snapshot.sha256)
    if planned.exists():
        if fingerprint(planned).sha256 == snapshot.sha256:
            return planned
        raise FileExistsError("预定移动目标已被不同内容占用，拒绝覆盖")
    temporary = planned.with_name(f".{uuid.uuid4().hex}.partial")
    shutil.copy2(source, temporary)
    if fingerprint(temporary).sha256 != snapshot.sha256:
        temporary.unlink(missing_ok=True)
        raise RuntimeError("复制后SHA256不一致，拒绝移动")
    os.replace(temporary, planned)
    source.unlink()
    return planned


def copy_verified(source: Path, destination_dir: Path, final_name: str, snapshot: Fingerprint, *, target: Path | None = None) -> Path:
    if not verify_snapshot(source, snapshot):
        raise FileChangedError("文件在操作前已变更，拒绝复制")
    destination_dir.mkdir(parents=True, exist_ok=True)
    planned = _planned_target(destination_dir, target, final_name, snapshot.sha256)
    if planned.exists():
        if fingerprint(planned).sha256 == snapshot.sha256:
            return planned
        raise FileExistsError("预定复制目标已被不同内容占用，拒绝覆盖")
    temporary = planned.with_name(f".{uuid.uuid4().hex}.partial")
    shutil.copy2(source, temporary)
    if fingerprint(temporary).sha256 != snapshot.sha256:
        temporary.unlink(missing_ok=True)
        raise RuntimeError("复制后SHA256不一致，拒绝归档")
    os.replace(temporary, planned)
    return planned


def crop_center_verified(source: Path, destination_dir: Path, final_name: str, snapshot: Fingerprint, numerator: int, denominator: int, *, target: Path | None = None) -> Path:
    """Create a centre-cropped production image without changing the master."""
    if not verify_snapshot(source, snapshot):
        raise FileChangedError("文件在操作前已变更，拒绝裁切")
    divisor = gcd(numerator, denominator)
    numerator, denominator = numerator // divisor, denominator // divisor
    destination_dir.mkdir(parents=True, exist_ok=True)
    planned = _planned_target(destination_dir, target, final_name, snapshot.sha256)
    temporary = planned.with_name(f".{uuid.uuid4().hex}{planned.suffix}.partial")
    try:
        with Image.open(source) as image:
            width, height = image.size
            if width * denominator >= height * numerator:
                crop_height = height - (height % denominator)
                crop_width = crop_height // denominator * numerator
            else:
                crop_width = width - (width % numerator)
                crop_height = crop_width // numerator * denominator
            if crop_width <= 0 or crop_height <= 0:
                raise ValueError("原图尺寸无法按指定比例裁切")
            left, top = (width - crop_width) // 2, (height - crop_height) // 2
            cropped = image.crop((left, top, left + crop_width, top + crop_height))
            if image.format == "JPEG" and cropped.mode not in ("RGB", "L"):
                cropped = cropped.convert("RGB")
            cropped.save(temporary, format=image.format)
        expected = fingerprint(temporary)
        if planned.exists():
            existing = fingerprint(planned)
            if existing.pixel_digest == expected.pixel_digest:
                return planned
            raise FileExistsError("预定裁切目标已被不同内容占用，拒绝覆盖")
        if not verify_snapshot(source, snapshot):
            raise FileChangedError("裁切期间原文件已变更，拒绝写入结果")
        os.replace(temporary, planned)
        return planned
    finally:
        temporary.unlink(missing_ok=True)


def delete_verified(source: Path, snapshot: Fingerprint, thumbnail_target: Path) -> Path:
    if not verify_snapshot(source, snapshot):
        raise FileChangedError("文件在操作前已变更，拒绝删除")
    evidence = thumbnail(source, thumbnail_target)
    if not verify_snapshot(source, snapshot):
        raise FileChangedError("取证后文件已变更，拒绝删除")
    source.unlink()
    if source.exists():
        raise RuntimeError("删除后文件仍存在")
    return evidence


def remove_empty_directory(directory: Path) -> bool:
    """Remove only an existing empty directory after the caller finished file work."""
    if not directory.is_dir() or any(directory.iterdir()):
        return False
    directory.rmdir()
    return True


def reconcile_incomplete_operations(session: Session) -> int:
    """Reconcile interrupted operations from physical evidence without guessing.

    The function never starts a new destructive action.  It only marks an
    operation complete if its target/evidence proves the action already landed;
    otherwise it remains a visible failure for a retry after fresh scanning.
    """
    reconciled = 0
    operations = session.scalars(select(FileOperation).where(FileOperation.state.in_(("PREPARED", "EXECUTING", "VERIFIED"))))
    for operation in operations:
        origin = Path(operation.origin_path) if operation.origin_path else None
        target = Path(operation.target_path) if operation.target_path else None
        proven = False
        try:
            if operation.operation in {"MOVE", "COPY"} and target and target.is_file():
                proven = fingerprint(target).sha256 == operation.origin_sha256
            elif operation.operation == "DELETE" and origin and not origin.exists() and operation.thumbnail_path and Path(operation.thumbnail_path).is_file():
                proven = True
        except OSError:
            proven = False
        if proven:
            operation.state = "DONE"
        else:
            operation.state = "FAILED"
            operation.error_text = "启动恢复无法从物理文件核验已完成操作；需要重新扫描后重试"
        reconciled += 1
    if reconciled:
        session.commit()
    return reconciled
