"""Non-destructive production crops derived from archived POD masters."""

import re
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.images import FileOperation, Image, ImageFile, TaskItem
from app.models.tasks import Task
from app.repositories.tasks import add_event
from app.services.ratios import normalize_ratio
from app.services.source_organize import _operation
from app.services.task_control import stop_if_cancelled
from app.storage.fingerprint import fingerprint, path_digest
from app.storage.safe_ops import crop_center_verified


_CANONICAL_NAME = re.compile(r"^(\d{8})(\d{9})(?:_\d+)?\.[^.]+$", re.IGNORECASE)


def production_filename(source: Path, ratio: str) -> str:
    """Keep the master name traceable while marking the derived ratio."""
    return f"{source.stem}_{ratio}{source.suffix}"


def canonical_master_date(path: Path) -> str | None:
    """Return YYYYMMDD from a system-generated POD master filename."""
    match = _CANONICAL_NAME.match(path.name)
    return match.group(1) if match else None


def _crop_sources(task: Task, session: Session, library: Path) -> list[tuple[ImageFile, Image]]:
    start, end = task.settings_snapshot.get("crop_start_date"), task.settings_snapshot.get("crop_end_date")
    if not isinstance(start, str) or not isinstance(end, str):
        raise ValueError("裁切任务缺少已冻结的时间范围")
    rows: list[tuple[ImageFile, Image]] = []
    files = session.scalars(select(ImageFile).where(ImageFile.role == "POD_MASTER", ImageFile.file_status == "PRESENT"))
    for file in files:
        path = Path(file.path)
        if path.parent.resolve(strict=False) != library.resolve(strict=False):
            continue
        master_date = canonical_master_date(path)
        if not master_date or not (start <= master_date <= end):
            continue
        image = session.get(Image, file.image_id)
        if image is not None:
            rows.append((file, image))
    return rows


def crop_production_images(task: Task, session: Session) -> None:
    if stop_if_cancelled(session, task):
        return
    library = Path(task.pod_library_dir or "")
    if not library.is_dir():
        task.status = "FAILED"; task.warnings = [*task.warnings, "历史POD图库不可访问，未执行裁切"]; session.commit(); return
    ratio = normalize_ratio(task.ratio_code or "")
    numerator, denominator = (int(value) for value in ratio.split("x"))
    if task.archive_date is None:
        task.archive_date = datetime.now(ZoneInfo(task.settings_snapshot.get("app_timezone", settings.app_timezone))).date()
        session.commit()
    output = library / "Production" / ratio / task.archive_date.strftime("%y%m%d")
    existing = {item.image_id: item for item in session.scalars(select(TaskItem).where(TaskItem.task_id == task.id))}
    sources = _crop_sources(task, session, library)
    for master_file, image in sources:
        if stop_if_cancelled(session, task):
            return
        if image.id in existing:
            continue
        session.add(TaskItem(task_id=task.id, image_id=image.id, observed_path=master_file.path, observed_path_digest=path_digest(Path(master_file.path)), stage="CROPPING", status="PENDING", snapshot_sha256=master_file.sha256, snapshot_size=master_file.size_bytes, snapshot_mtime_ns=master_file.mtime_ns))
    session.commit()

    generated = errors = 0
    for item in session.scalars(select(TaskItem).where(TaskItem.task_id == task.id, TaskItem.status == "PENDING")):
        if stop_if_cancelled(session, task):
            return
        source, image = Path(item.observed_path), session.get(Image, item.image_id)
        if image is None or not source.is_file():
            item.status = "ERROR"; item.error_code = "MASTER_MISSING"; item.error_message = "历史POD主文件不存在"; errors += 1; session.commit(); continue
        snapshot = fingerprint(source)
        if snapshot.sha256 != item.snapshot_sha256 or snapshot.size_bytes != item.snapshot_size:
            item.status = "ERROR"; item.error_code = "FILE_CHANGED"; item.error_message = "历史POD主文件身份已变化"; errors += 1; session.commit(); continue
        if task.settings_snapshot.get("dry_run", False):
            item.status = "WOULD_CROP"; generated += 1; session.commit(); continue
        operation = session.scalar(select(FileOperation).where(FileOperation.task_item_id == item.id, FileOperation.reason == "POD_PRODUCTION_CROP"))
        filename = production_filename(source, ratio)
        target = output / filename
        if operation is None:
            operation = _operation(session, task, item, image, "DERIVE", source, snapshot, "POD_PRODUCTION_CROP", target)
        try:
            operation.state = "EXECUTING"; session.commit()
            created = crop_center_verified(source, output, filename, snapshot, numerator, denominator, target=target)
            result = fingerprint(created)
            production = session.scalar(select(ImageFile).where(ImageFile.normalized_path_digest == path_digest(created)))
            if production is None:
                session.add(ImageFile(image_id=image.id, role="POD_PRODUCTION", path=str(created), normalized_path_digest=path_digest(created), size_bytes=result.size_bytes, mtime_ns=result.mtime_ns, sha256=result.sha256, file_status="PRESENT", archive_date=task.archive_date, ratio_code=ratio))
            else:
                production.file_status = "PRESENT"; production.mtime_ns = result.mtime_ns
            operation.state = "DONE"; item.status = "CROP_CREATED"; generated += 1
        except Exception as error:
            operation.state = "FAILED"; operation.error_text = str(error); item.status = "ERROR"; item.error_code = "CROP_FAILED"; item.error_message = str(error); errors += 1
        session.commit()
    if stop_if_cancelled(session, task):
        return
    task.counters = {**task.counters, "processed": generated + errors, "archived": generated, "errors": errors}
    task.status = "PARTIAL_COMPLETED" if errors else "DONE"; task.finished_at = datetime.now(UTC).replace(tzinfo=None); task.lease_until = None
    add_event(session, task, "INFO", task.status, "POD生产素材居中裁切完成")
    session.commit()
