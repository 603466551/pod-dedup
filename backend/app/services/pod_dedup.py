"""Conservative POD deduplication: exact deletion, visual review, then archive."""

from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.runtime import write_worker_heartbeat
from app.dedup.common.embedding import VisualUnavailableError
from app.dedup.pod.retriever import pod_candidates
from app.indexing.catalog import catalog_library, feature_for_path, model_namespace, pod_index_path, rebuild_pod_index, query_vector
from app.models.images import DuplicatePair, FileOperation, Image, ImageFile, Review, TaskItem
from app.models.tasks import Task
from app.repositories.tasks import add_event
from app.services.source_organize import IMAGE_EXTENSIONS, _historical_fingerprints, _is_exact_duplicate, _operation, organize
from app.services.task_control import stop_if_cancelled
from app.services.feedback import reused_review
from app.storage.fingerprint import fingerprint, path_digest
from app.storage.safe_ops import copy_verified, delete_verified, move_verified, plan_target, timestamped_filename
from app.vlm.client import VlmUnavailableError, compare

RATIOS = {"3x4": (3, 4, "Portrait"), "9x16": (9, 16, "Portrait"), "1x1": (1, 1, "Square"), "4x3": (4, 3, "Landscape"), "16x9": (16, 9, "Landscape")}


def _task_setting(task: Task, name: str, default):
    return task.settings_snapshot.get(name, default)


def ratio_matches(width: int, height: int, code: str, tolerance: float) -> bool:
    numerator, denominator, _ = RATIOS[code]
    return abs((width / height) / (numerator / denominator) - 1) <= tolerance


def _add_pending_file(session: Session, image: Image, source: Path, snapshot) -> ImageFile:
    file = ImageFile(image_id=image.id, role="POD_PENDING", path=str(source), normalized_path_digest=path_digest(source), size_bytes=snapshot.size_bytes, mtime_ns=snapshot.mtime_ns, sha256=snapshot.sha256, file_status="PRESENT")
    session.add(file)
    return file


def _matches_operation_target(path: Path, operation: FileOperation) -> bool:
    try:
        return path.is_file() and fingerprint(path).sha256 == operation.origin_sha256
    except OSError:
        return False


def _planned_operation(task: Task, item: TaskItem, image: Image, session: Session, kind: str, source: Path, snapshot, reason: str, directory: Path, name: str) -> tuple[FileOperation, Path]:
    operation = session.scalar(select(FileOperation).where(FileOperation.task_item_id == item.id, FileOperation.reason == reason))
    if operation is not None:
        if not operation.target_path:
            raise RuntimeError("历史操作缺少预定目标路径，拒绝猜测恢复")
        return operation, Path(operation.target_path)
    target = plan_target(directory, name, snapshot.sha256)
    return _operation(session, task, item, image, kind, source, snapshot, reason, target), target


def _upsert_classified_file(session: Session, image: Image, classified: Path, snapshot, task: Task) -> None:
    file = session.scalar(select(ImageFile).where(ImageFile.normalized_path_digest == path_digest(classified)))
    if file is None:
        session.add(ImageFile(image_id=image.id, role="POD_CLASSIFIED", path=str(classified), normalized_path_digest=path_digest(classified), size_bytes=snapshot.size_bytes, mtime_ns=classified.stat().st_mtime_ns, sha256=snapshot.sha256, file_status="PRESENT", archive_date=task.archive_date, ratio_code=task.ratio_code))
        return
    file.file_status = "PRESENT"; file.path = str(classified); file.mtime_ns = classified.stat().st_mtime_ns


def _archive_item(task: Task, item: TaskItem, image: Image, pending_file: ImageFile, session: Session, library: Path) -> None:
    source = Path(pending_file.path)
    if pending_file.role == "POD_MASTER":
        master = source
        snapshot = fingerprint(master)
        if snapshot.sha256 != item.snapshot_sha256 or snapshot.size_bytes != item.snapshot_size:
            raise RuntimeError("已归档POD主文件身份已变化，拒绝继续复制")
    else:
        source_snapshot = fingerprint(source) if source.exists() else None
        if source_snapshot is not None and (source_snapshot.sha256 != item.snapshot_sha256 or source_snapshot.size_bytes != item.snapshot_size):
            raise RuntimeError("待归档POD文件身份已变化，拒绝移动")
        if source_snapshot is not None:
            move_op, planned_master = _planned_operation(task, item, image, session, "MOVE", source, source_snapshot, "POD_MASTER_ARCHIVE", library, timestamped_filename(source))
        else:
            move_op = session.scalar(select(FileOperation).where(FileOperation.task_item_id == item.id, FileOperation.reason == "POD_MASTER_ARCHIVE"))
            if move_op is None or not move_op.target_path:
                raise RuntimeError("待归档POD已缺失且不存在可核验的移动操作")
            planned_master = Path(move_op.target_path)
        if _matches_operation_target(planned_master, move_op):
            master = planned_master
        elif source_snapshot is not None:
            move_op.state = "EXECUTING"; session.commit()
            master = move_verified(source, library, source_snapshot, target=planned_master)
        else:
            raise RuntimeError("移动操作目标不存在，且原待处理POD也不存在")
        move_op.state = "DONE"
        snapshot = fingerprint(master)
        pending_file.role = "POD_MASTER"; pending_file.path = str(master); pending_file.normalized_path_digest = path_digest(master); pending_file.mtime_ns = master.stat().st_mtime_ns; pending_file.ratio_code = task.ratio_code
        image.status = "LIBRARY"; image.original_filename = master.name
    if not task.ratio_code:
        item.status = "ARCHIVED"
        return
    _, _, direction = RATIOS[task.ratio_code or "3x4"]
    classified_dir = library / direction / (task.ratio_code or "3x4") / task.archive_date.strftime("%y%m%d")
    copy_op, planned_classified = _planned_operation(task, item, image, session, "COPY", master, snapshot, "POD_CLASSIFIED_ARCHIVE", classified_dir, master.name)
    if _matches_operation_target(planned_classified, copy_op):
        classified = planned_classified
    else:
        copy_op.state = "EXECUTING"; session.commit()
        classified = copy_verified(master, classified_dir, master.name, snapshot, target=planned_classified)
    copy_op.state = "DONE"
    _upsert_classified_file(session, image, classified, snapshot, task)
    item.status = "ARCHIVED"


def archive_ready_items(task: Task, session: Session, thumbnails_dir: Path) -> tuple[int, int]:
    """Perform the move/copy phase only after every required review is closed."""
    library = Path(task.pod_library_dir or "")
    archived = failures = 0
    if not library.is_dir():
        return archived, 1
    ready = list(session.scalars(select(TaskItem).where(TaskItem.task_id == task.id, TaskItem.status == "READY_TO_ARCHIVE")))
    if task.settings_snapshot.get("dry_run", False):
        for item in ready:
            if stop_if_cancelled(session, task):
                return archived, failures
            item.status = "WOULD_ARCHIVE"
        if ready:
            task.counters = {**task.counters, "would_archive": task.counters.get("would_archive", 0) + len(ready)}
            session.commit()
        return 0, 0
    if ready and task.archive_date is None:
        # F01: freeze once when the unified archive actually begins, not when
        # the batch was scanned or when its task was created.
        task.archive_date = datetime.now(ZoneInfo(_task_setting(task, "app_timezone", settings.app_timezone))).date()
        session.commit()
    for item in ready:
        if stop_if_cancelled(session, task):
            return archived, failures
        image = session.get(Image, item.image_id)
        pending_file = session.scalar(select(ImageFile).where(ImageFile.image_id == item.image_id, ImageFile.role.in_(("POD_PENDING", "POD_MASTER")), ImageFile.file_status == "PRESENT"))
        if not image or not pending_file:
            item.status = "ERROR"; item.error_code = "PENDING_FILE_MISSING"; item.error_message = "待归档POD文件登记不存在"; failures += 1; session.commit(); continue
        try:
            _archive_item(task, item, image, pending_file, session, library); archived += 1
        except Exception as error:
            item.status = "ERROR"; item.error_code = "ARCHIVE_FAILED"; item.error_message = str(error); failures += 1
        session.commit()
    return archived, failures


def _recover_archive_intents(task: Task, session: Session) -> None:
    """Finish database checkpoints for pre-persisted archive targets after a stop."""
    changed = False
    for item in session.scalars(select(TaskItem).where(TaskItem.task_id == task.id)):
        if item.image_id is None:
            continue
        image = session.get(Image, item.image_id)
        file = session.scalar(select(ImageFile).where(ImageFile.image_id == item.image_id, ImageFile.role.in_(("POD_PENDING", "POD_MASTER")), ImageFile.file_status == "PRESENT"))
        if image is None or file is None:
            continue
        if file.role == "POD_PENDING":
            move_op = session.scalar(select(FileOperation).where(FileOperation.task_item_id == item.id, FileOperation.reason == "POD_MASTER_ARCHIVE"))
            if move_op and move_op.target_path and _matches_operation_target(Path(move_op.target_path), move_op):
                master = Path(move_op.target_path)
                move_op.state = "DONE"; file.role = "POD_MASTER"; file.path = str(master); file.normalized_path_digest = path_digest(master); file.mtime_ns = master.stat().st_mtime_ns; file.ratio_code = task.ratio_code; image.status = "LIBRARY"; image.original_filename = master.name; item.status = "READY_TO_ARCHIVE"; changed = True
        if file.role == "POD_MASTER" and not task.ratio_code:
            item.status = "ARCHIVED"; changed = True
        elif file.role == "POD_MASTER":
            copy_op = session.scalar(select(FileOperation).where(FileOperation.task_item_id == item.id, FileOperation.reason == "POD_CLASSIFIED_ARCHIVE"))
            if copy_op and copy_op.target_path and _matches_operation_target(Path(copy_op.target_path), copy_op):
                master_snapshot = fingerprint(Path(file.path))
                copy_op.state = "DONE"; _upsert_classified_file(session, image, Path(copy_op.target_path), master_snapshot, task); item.status = "ARCHIVED"; changed = True
    if changed:
        session.commit()


def finalize_reviewed_task(task: Task, session: Session, thumbnails_dir: Path) -> None:
    """F09: the final review releases the entire frozen batch for one archive pass."""
    if session.scalar(select(Review.id).where(Review.task_id == task.id, Review.status == "PENDING")) is not None:
        return
    for item in session.scalars(select(TaskItem).where(TaskItem.task_id == task.id, TaskItem.status == "WAIT_REVIEW")):
        image = session.get(Image, item.image_id)
        if image and image.status != "DELETED":
            item.status = "READY_TO_ARCHIVE"
    session.commit()
    archived, failures = archive_ready_items(task, session, thumbnails_dir)
    counters = dict(task.counters); counters["archived"] = counters.get("archived", 0) + archived; counters["errors"] = counters.get("errors", 0) + failures
    task.counters = counters; task.status = "PARTIAL_COMPLETED" if failures else "DONE"; task.finished_at = datetime.now(UTC).replace(tzinfo=None); task.lease_until = None
    add_event(session, task, "INFO", task.status, "全部POD审核结束，已执行统一归档")
    session.commit()


def _create_visual_reviews(task: Task, item: TaskItem, image: Image, source: Path, candidates: list[dict], session: Session) -> int:
    created = 0
    for candidate in candidates:
        same_ratio = candidate["ratio_code"] in (None, task.ratio_code)
        prior = reused_review(session, new_sha256=image.sha256, match_image_id=candidate["image_id"])
        pair = DuplicatePair(task_id=task.id, image_new_id=image.id, image_match_id=candidate["image_id"], pair_type="POD_POD", machine_decision="RETRIEVED_CANDIDATE", rule_id="POD_DINOV2_RETRIEVAL_V1", evidence_json={"cosine_similarity": candidate["score"], "feature_id": candidate["feature_id"], "candidate_path": candidate["path"], "candidate_ratio_code": candidate["ratio_code"]}, review_required=same_ratio, resolution_status="PENDING" if same_ratio else "RATIO_PROTECTED")
        if prior:
            pair.machine_decision = "REUSED_HUMAN_DECISION"
            pair.evidence_json = {**pair.evidence_json, "reused_human_review": prior}
            pair.review_required = False
            pair.resolution_status = "RESOLVED_REUSED"
        session.add(pair)
        session.flush()
        if not prior:
            try:
                pair.evidence_json = {**pair.evidence_json, "vlm": compare(session, task_id=task.id, pair_id=pair.id, pair_type="POD_POD", new_path=source, match_path=Path(candidate["path"])).as_dict()}
            except VlmUnavailableError as error:
                pair.evidence_json = {**pair.evidence_json, "vlm_status": str(error)}
        if same_ratio and not prior:
            session.add(Review(pair_id=pair.id, task_id=task.id, status="PENDING")); created += 1
    if created:
        item.status = "WAIT_REVIEW"
    return created


def _frozen_manifest(task: Task, pending: Path, session: Session) -> list[tuple[Path, TaskItem]]:
    """Persist F06's batch boundary before any action can change the folder."""
    existing = [item for item in session.scalars(select(TaskItem).where(TaskItem.task_id == task.id).order_by(TaskItem.id)) if Path(item.observed_path).parent == pending]
    if existing:
        return [(Path(item.observed_path), item) for item in existing]
    items: list[tuple[Path, TaskItem]] = []
    for source in sorted(pending.iterdir(), key=lambda entry: entry.name.casefold()):
        if stop_if_cancelled(session, task):
            return items
        write_worker_heartbeat()
        if not source.is_file() or source.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        try:
            snapshot = fingerprint(source)
            item = TaskItem(task_id=task.id, observed_path=str(source), observed_path_digest=path_digest(source), stage="FROZEN", status="PENDING", snapshot_sha256=snapshot.sha256, snapshot_size=snapshot.size_bytes, snapshot_mtime_ns=snapshot.mtime_ns)
        except OSError as error:
            item = TaskItem(task_id=task.id, observed_path=str(source), observed_path_digest=path_digest(source), stage="FROZEN", status="ERROR", error_code="SCAN_FAILED", error_message=str(error))
        session.add(item)
        items.append((source, item))
        # Hashing and decoding a large MJ batch can take minutes.  Persist in
        # small checkpoints so the UI has honest progress and a restart does
        # not discard the whole frozen manifest.
        if len(items) % 10 == 0:
            task.counters = {**task.counters, "scanned": len(items)}
            session.commit()
    session.commit()
    task.counters = {**task.counters, "scanned": len(items)}
    session.commit()
    return items


def deduplicate_and_archive(task: Task, session: Session, thumbnails_dir: Path) -> None:
    if stop_if_cancelled(session, task):
        return
    pending, library = Path(task.pod_pending_dir or ""), Path(task.pod_library_dir or "")
    if not pending.is_dir() or not library.is_dir():
        task.status = "FAILED"; task.warnings = [*task.warnings, "POD待处理目录或图库不可访问"]; session.commit(); return
    if task.source_batch_dir and task.source_library_dir:
        source_failures = organize(task, session, thumbnails_dir, finalize_task=False)
        if stop_if_cancelled(session, task):
            return
        if source_failures:
            task.warnings = [*task.warnings, f"自动来源整理有{source_failures}项失败；已继续处理不受影响的POD"]
    else:
        add_event(session, task, "INFO", "SOURCE_ORGANIZING", "MJ POD直入模式：未提供来源目录，已跳过来源整理")
    session.commit()

    # F06: the first scan persists the complete batch boundary. A restarted
    # task reads these rows instead of noticing files added later.
    manifest = _frozen_manifest(task, pending, session)
    if stop_if_cancelled(session, task):
        return
    _recover_archive_intents(task, session)
    historical = _historical_fingerprints(library)
    def catalog_progress(indexed: int) -> None:
        write_worker_heartbeat()
        if indexed % 10 == 0:
            task.counters = {**task.counters, "cataloged": indexed}
            session.commit()

    try:
        catalog_library(session, library, progress=catalog_progress); session.commit(); rebuild_pod_index(session)
    except VisualUnavailableError as error:
        task.warnings = [*task.warnings, str(error)]; session.commit()
    except ValueError:
        # An empty library has no index; the first successfully embedded batch item creates it.
        pass
    if stop_if_cancelled(session, task):
        return

    failures = deleted = processed = reviews = 0
    dry_run = bool(task.settings_snapshot.get("dry_run", False))
    model_id, revision, preprocess = model_namespace()
    terminal_items = {"AUTO_DELETED", "ARCHIVED", "WOULD_DELETE", "WOULD_ARCHIVE", "RATIO_MISMATCH"}
    for source, item in manifest:
        if stop_if_cancelled(session, task):
            return
        if item.status in terminal_items:
            continue
        master_file = session.scalar(select(ImageFile).where(ImageFile.image_id == item.image_id, ImageFile.role == "POD_MASTER", ImageFile.file_status == "PRESENT")) if item.image_id else None
        if master_file is not None:
            item.status = "READY_TO_ARCHIVE"; session.commit(); continue
        if not source.exists():
            item.status = "ERROR"; item.error_code = "FROZEN_FILE_MISSING"; item.error_message = "冻结清单中的文件已不存在"; failures += 1; session.commit(); continue
        try:
            snapshot = fingerprint(source)
        except OSError as error:
            failures += 1; add_event(session, task, "ERROR", "SCANNING", f"无法解码POD：{source.name}：{error}"); session.commit(); continue
        if item.snapshot_sha256 and (snapshot.sha256 != item.snapshot_sha256 or snapshot.size_bytes != item.snapshot_size or snapshot.mtime_ns != item.snapshot_mtime_ns):
            item.status = "ERROR"; item.error_code = "FILE_CHANGED"; item.error_message = "文件在冻结后已变化，拒绝继续处理"; failures += 1; session.commit(); continue
        image = session.get(Image, item.image_id) if item.image_id else None
        if image is None:
            image = Image(kind="POD", original_filename=source.name, sha256=snapshot.sha256, pixel_digest=snapshot.pixel_digest, width=snapshot.width, height=snapshot.height, file_size=snapshot.size_bytes, status="PENDING")
            session.add(image); session.flush(); item.image_id = image.id
        item.stage = "DECIDING"; item.status = "CHECKING"
        pending_file = session.scalar(select(ImageFile).where(ImageFile.image_id == image.id, ImageFile.role == "POD_PENDING", ImageFile.file_status == "PRESENT"))
        if pending_file is None:
            pending_file = _add_pending_file(session, image, source, snapshot)
        if task.ratio_code and not ratio_matches(snapshot.width, snapshot.height, task.ratio_code, _task_setting(task, "ratio_rel_tolerance", settings.ratio_rel_tolerance)):
            item.status = "RATIO_MISMATCH"; session.commit(); continue
        if _is_exact_duplicate(snapshot, historical):
            pair = DuplicatePair(task_id=task.id, image_new_id=image.id, image_match_id=None, pair_type="POD_POD", machine_decision="EXACT_DUPLICATE", rule_id="POD_EXACT", evidence_json={"sha256": snapshot.sha256.hex(), "pixel_digest": snapshot.pixel_digest.hex()}, review_required=False, resolution_status="AUTO_DELETED")
            session.add(pair); session.flush()
            if dry_run:
                item.status = "WOULD_DELETE"; historical.append(snapshot); processed += 1; session.commit(); continue
            operation = _operation(session, task, item, image, "DELETE", source, snapshot, "POD_EXACT_DUPLICATE")
            try:
                operation.thumbnail_path = str(delete_verified(source, snapshot, thumbnails_dir / f"{operation.id}.jpg")); operation.state = "DONE"; item.status = "AUTO_DELETED"; image.status = "DELETED"; pending_file.file_status = "DELETED"; deleted += 1
            except Exception as error:
                operation.state = "FAILED"; operation.error_text = str(error); item.status = "ERROR"; failures += 1
            session.commit(); continue
        try:
            vector = query_vector(source)
            candidates = pod_candidates(session, index_path=pod_index_path(), query=vector, top_k=_task_setting(task, "retrieval_top_k", settings.retrieval_top_k), model_id=model_id, revision=revision, preprocess=preprocess, exclude_image_id=image.id)
            candidates = [candidate for candidate in candidates if candidate["score"] >= _task_setting(task, "retrieval_candidate_min_similarity", settings.retrieval_candidate_min_similarity)]
            reviews += _create_visual_reviews(task, item, image, source, candidates, session)
            feature_for_path(session, image=image, path=source); rebuild_pod_index(session)
        except VisualUnavailableError as error:
            if str(error) not in task.warnings:
                task.warnings = [*task.warnings, str(error)]
        except Exception as error:
            item.status = "ERROR"; item.error_code = "VISUAL_INDEX_FAILED"; item.error_message = str(error); failures += 1
        if item.status == "CHECKING":
            item.status = "READY_TO_ARCHIVE"
        historical.append(snapshot); processed += 1; session.commit()

    if stop_if_cancelled(session, task):
        return
    if reviews:
        task.counters = {
            **task.counters,
            "processed": task.counters.get("processed", 0) + processed,
            "deleted": task.counters.get("deleted", 0) + deleted,
            "waiting_review": task.counters.get("waiting_review", 0) + reviews,
            "errors": task.counters.get("errors", 0) + failures,
        }; task.status = "WAIT_REVIEW"; task.lease_until = None
        add_event(session, task, "INFO", task.status, "视觉候选已创建人工审核；本批POD将在最后一条审核后统一归档")
        session.commit(); return
    archived, archive_failures = archive_ready_items(task, session, thumbnails_dir)
    if stop_if_cancelled(session, task):
        return
    failures += archive_failures
    task.counters = {
        **task.counters,
        "processed": task.counters.get("processed", 0) + processed,
        "deleted": task.counters.get("deleted", 0) + deleted,
        "archived": task.counters.get("archived", 0) + archived,
        "errors": task.counters.get("errors", 0) + failures,
    }; task.status = "PARTIAL_COMPLETED" if failures else "DONE"; task.finished_at = datetime.now(UTC).replace(tzinfo=None); task.lease_until = None
    add_event(session, task, "INFO", task.status, "POD精确去重、DINOv2候选召回与归档完成")
    session.commit()
