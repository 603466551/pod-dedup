"""M2 exact-only organization of external-AI successful source images."""

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.images import FileOperation, Image, ImageFile, TaskItem
from app.models.tasks import Task
from app.repositories.tasks import add_event
from app.services.task_control import stop_if_cancelled
from app.storage.fingerprint import Fingerprint, fingerprint, path_digest
from app.storage.safe_ops import delete_verified, move_verified, plan_target, remove_empty_directory, timestamped_filename

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}


def _supported(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS


def _historical_fingerprints(library: Path) -> list[Fingerprint]:
    results: list[Fingerprint] = []
    for candidate in library.iterdir():
        if _supported(candidate):
            try:
                results.append(fingerprint(candidate))
            except OSError:
                continue
    return results


def _is_exact_duplicate(current: Fingerprint, historical: list[Fingerprint]) -> bool:
    return any(
        current.sha256 == old.sha256 or current.pixel_digest == old.pixel_digest for old in historical
    )


def _operation(session: Session, task: Task, item: TaskItem, image: Image, kind: str, source: Path, snapshot: Fingerprint, reason: str, target: Path | None = None) -> FileOperation:
    operation = FileOperation(
        task_id=task.id, task_item_id=item.id, image_id=image.id, operation=kind,
        origin_path=str(source), target_path=str(target) if target else None, origin_sha256=snapshot.sha256, expected_size=snapshot.size_bytes,
        operation_key=f"{task.id}:{item.id}:{kind}:SOURCE", state="PREPARED", reason=reason,
    )
    session.add(operation)
    session.commit()  # Persist evidence before the irreversible filesystem action.
    return operation


def _upsert_source_library_file(
    session: Session,
    *,
    image: Image,
    item: TaskItem,
    operation: FileOperation,
    target: Path,
    snapshot: Fingerprint,
) -> None:
    """Record a verified library file without violating the canonical path key.

    A previous interrupted run or a manual library re-index can already own the
    path digest.  When it is the same bytes, retain that image identity; when
    the on-disk path has been reused for different verified bytes, update the
    existing path record to point at the new image identity.
    """
    normalized_digest = path_digest(target)
    file = session.scalar(
        select(ImageFile).where(ImageFile.normalized_path_digest == normalized_digest)
    )
    if file is not None and file.sha256 == snapshot.sha256:
        existing_image = session.get(Image, file.image_id)
        if existing_image is not None:
            item.image_id = existing_image.id
            operation.image_id = existing_image.id
            session.flush()
            session.delete(image)
            existing_image.status = "LIBRARY"
    elif file is None:
        file = ImageFile(
            image_id=image.id,
            role="SOURCE_LIBRARY",
            path=str(target),
            normalized_path_digest=normalized_digest,
            size_bytes=snapshot.size_bytes,
            mtime_ns=snapshot.mtime_ns,
            sha256=snapshot.sha256,
            file_status="PRESENT",
        )
        session.add(file)
    else:
        # The physical path was recreated with different bytes.  The unique
        # path record must follow the verified current file, not stale metadata.
        file.image_id = image.id

    file.role = "SOURCE_LIBRARY"
    file.path = str(target)
    file.size_bytes = snapshot.size_bytes
    file.mtime_ns = snapshot.mtime_ns
    file.sha256 = snapshot.sha256
    file.file_status = "PRESENT"


def _recover_source_moves(task: Task, session: Session) -> int:
    """Complete source-library metadata only when a preplanned target proves a move landed."""
    recovered = 0
    operations = session.scalars(select(FileOperation).where(FileOperation.task_id == task.id, FileOperation.reason == "SOURCE_PROCESSED_TO_LIBRARY"))
    for operation in operations:
        if not operation.target_path or operation.task_item_id is None or operation.image_id is None:
            continue
        target = Path(operation.target_path)
        try:
            snapshot = fingerprint(target)
        except OSError:
            continue
        if snapshot.sha256 != operation.origin_sha256:
            continue
        item, image = session.get(TaskItem, operation.task_item_id), session.get(Image, operation.image_id)
        if item is None or image is None:
            continue
        operation.state = "DONE"; item.status = "ARCHIVED_SOURCE"; image.status = "LIBRARY"; image.original_filename = target.name
        _upsert_source_library_file(
            session, image=image, item=item, operation=operation, target=target, snapshot=snapshot
        )
        recovered += 1
    if recovered:
        session.commit()
    return recovered


def organize(task: Task, session: Session, thumbnails_dir: Path, *, finalize_task: bool = True) -> int:
    if stop_if_cancelled(session, task):
        return 0
    batch = Path(task.source_batch_dir or "")
    library = Path(task.source_library_dir or "")
    processed = batch / "已处理"
    if not library.is_dir():
        task.warnings = [*task.warnings, "历史源图库不可访问，未执行来源整理"]
        if finalize_task:
            task.status = "FAILED"
        session.commit()
        return 1
    recovered = _recover_source_moves(task, session)
    if not processed.is_dir():
        task.warnings = [*task.warnings, "无待整理来源"]
        task.counters = {**task.counters, "processed": task.counters.get("processed", 0) + recovered}
        if finalize_task:
            task.status = "DONE"
        session.commit()
        return 0
    historical = _historical_fingerprints(library)
    dry_run = bool(task.settings_snapshot.get("dry_run", False))
    failures = 0
    processed_count = 0
    deleted_count = 0
    for source in list(processed.iterdir()):
        if stop_if_cancelled(session, task):
            return failures
        if not _supported(source):
            continue
        try:
            snapshot = fingerprint(source)
        except OSError as error:
            failures += 1
            add_event(session, task, "ERROR", "SOURCE_ORGANIZING", f"无法解码来源图：{source.name}：{error}")
            session.commit()
            continue
        image = Image(kind="SOURCE", original_filename=source.name, sha256=snapshot.sha256,
                      pixel_digest=snapshot.pixel_digest, width=snapshot.width, height=snapshot.height,
                      file_size=snapshot.size_bytes, status="PENDING")
        session.add(image); session.flush()
        item = TaskItem(task_id=task.id, image_id=image.id, observed_path=str(source),
                        observed_path_digest=path_digest(source), stage="SOURCE_ORGANIZING", status="MOVING",
                        snapshot_sha256=snapshot.sha256, snapshot_size=snapshot.size_bytes, snapshot_mtime_ns=snapshot.mtime_ns)
        session.add(item); session.flush()
        if _is_exact_duplicate(snapshot, historical):
            if dry_run:
                item.status = "WOULD_DELETE"; processed_count += 1; session.commit(); continue
            operation = _operation(session, task, item, image, "DELETE", source, snapshot, "SOURCE_EXACT_DUPLICATE")
            try:
                operation.thumbnail_path = str(delete_verified(source, snapshot, thumbnails_dir / f"{operation.id}.jpg"))
                operation.state = "DONE"; item.status = "DUPLICATE_DELETED"; image.status = "DELETED"; deleted_count += 1
            except Exception as error:
                operation.state = "FAILED"; operation.error_text = str(error); item.status = "ERROR"; failures += 1
            session.commit(); processed_count += 1
            continue
        if dry_run:
            item.status = "WOULD_MOVE"; processed_count += 1; historical.append(snapshot); session.commit(); continue
        target = plan_target(library, timestamped_filename(source), snapshot.sha256)
        operation = _operation(session, task, item, image, "MOVE", source, snapshot, "SOURCE_PROCESSED_TO_LIBRARY", target)
        try:
            operation.state = "EXECUTING"; session.commit()
            target = move_verified(source, library, snapshot, target=target)
            operation.target_path = str(target); operation.state = "DONE"; item.status = "ARCHIVED_SOURCE"; image.status = "LIBRARY"
            image.original_filename = target.name
            target_snapshot = fingerprint(target)
            _upsert_source_library_file(
                session,
                image=image,
                item=item,
                operation=operation,
                target=target,
                snapshot=target_snapshot,
            )
            historical.append(target_snapshot); processed_count += 1
        except Exception as error:
            operation.state = "FAILED"; operation.error_text = str(error); item.status = "ERROR"; failures += 1
        session.commit()
    if stop_if_cancelled(session, task):
        return failures
    if not dry_run:
        remove_empty_directory(processed)
        remove_empty_directory(batch)
    task.counters = {
        **task.counters,
        "processed": processed_count + recovered,
        "deleted": task.counters.get("deleted", 0) + deleted_count,
        "errors": failures,
    }
    if finalize_task:
        task.status = "PARTIAL_COMPLETED" if failures else "DONE"
        add_event(session, task, "INFO", task.status, "来源已处理整理完成")
    else:
        add_event(session, task, "WARNING" if failures else "INFO", "SOURCE_ORGANIZING", "POD任务的自动来源整理完成")
    session.commit()
    return failures
