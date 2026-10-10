"""Source deduplication with exact deletion and conservative visual retrieval."""

from pathlib import Path

import numpy as np
from PIL import Image as PillowImage
from sqlalchemy.orm import Session

from app.core.config import settings
from app.dedup.common.embedding import VisualUnavailableError
from app.dedup.common.retriever import retrieve
from app.dedup.source.roi import locate_print_region
from app.dedup.source.local_verify import verify_print_correspondence
from app.indexing.catalog import (
    SOURCE_FULL,
    SOURCE_PRINT,
    catalog_source_library,
    feature_for_value,
    index_path,
    model_namespace,
    rebuild_scope_index,
)
from app.models.images import DuplicatePair, FileOperation, Image, TaskItem
from app.models.tasks import Task
from app.repositories.tasks import add_event
from app.services.task_control import stop_if_cancelled
from app.services.source_organize import IMAGE_EXTENSIONS, _historical_fingerprints, _is_exact_duplicate, _operation
from app.storage.fingerprint import fingerprint, path_digest
from app.storage.safe_ops import delete_verified
from app.vlm.client import VlmUnavailableError, compare


def _vector(feature) -> np.ndarray:
    return np.frombuffer(feature.vector_blob, dtype="<f4").copy()


def _task_setting(task: Task, name: str, default):
    return task.settings_snapshot.get(name, default)


def _record_candidates(task: Task, image: Image, source: Path, new_bbox: dict | None, candidates: list[dict], session: Session) -> tuple[int, DuplicatePair | None]:
    recorded = 0
    approved: DuplicatePair | None = None
    seen: set[tuple[int, str]] = set()
    for candidate in candidates:
        key = (candidate["image_id"], candidate["scope"])
        if key in seen:
            continue
        seen.add(key)
        pair = DuplicatePair(
            task_id=task.id, image_new_id=image.id, image_match_id=candidate["image_id"],
            pair_type="SOURCE_SOURCE",
            machine_decision="RETRIEVED_CANDIDATE", rule_id="SOURCE_DINOV2_RETRIEVAL_V1",
            evidence_json={"cosine_similarity": candidate["score"], "feature_id": candidate["feature_id"], "candidate_path": candidate["path"], "retrieval_scope": candidate["scope"], "candidate_bbox": candidate["bbox"]},
            review_required=False, resolution_status="CANDIDATE_RETAINED",
        )
        session.add(pair); session.flush()
        try:
            vlm = compare(session, task_id=task.id, pair_id=pair.id, pair_type=pair.pair_type, new_path=source, match_path=Path(candidate["path"]))
            pair.evidence_json = {**pair.evidence_json, "vlm": vlm.as_dict()}
            if candidate["scope"] == SOURCE_PRINT:
                try:
                    local = verify_print_correspondence(source, Path(candidate["path"]), new_bbox, candidate["bbox"])
                except Exception as error:
                    local = {"valid": False, "reason": f"local_verification_failed:{error}"}
                pair.evidence_json = {**pair.evidence_json, "local_print_correspondence": local}
                if (
                    _task_setting(task, "source_visual_auto_delete", settings.source_visual_auto_delete)
                    and _task_setting(task, "source_visual_rule_validated", settings.source_visual_rule_validated)
                    and vlm.verdict == "same"
                    and vlm.print_region_valid
                    and not vlm.new_important_details
                    and local["valid"]
                ):
                    pair.machine_decision = "SOURCE_VISUAL_HIGH_CONFIRMED"
                    pair.rule_id = "SOURCE_VISUAL_HIGH_CONFIRMED_V1"
                    approved = pair
        except VlmUnavailableError as error:
            pair.evidence_json = {**pair.evidence_json, "vlm_status": str(error)}
        recorded += 1
    return recorded, approved


def _visual_candidates(task: Task, image: Image, source: Path, session: Session) -> tuple[int, DuplicatePair | None]:
    model_id, revision, preprocess = model_namespace()
    full_feature = feature_for_value(session, image=image, scope=SOURCE_FULL, value=source)
    candidates = retrieve(session, scope=SOURCE_FULL, index_path=index_path(SOURCE_FULL), query=_vector(full_feature), top_k=_task_setting(task, "retrieval_top_k", settings.retrieval_top_k), model_id=model_id, revision=revision, preprocess=preprocess, allowed_roles=("SOURCE_LIBRARY",), exclude_image_id=image.id)
    region = locate_print_region(source)
    if region is None:
        task.warnings = [*task.warnings, f"ROI_UNAVAILABLE:{source.name}"]
        return _record_candidates(task, image, source, None, candidates, session)
    with PillowImage.open(source) as opened:
        crop = opened.convert("RGB").crop((region.x, region.y, region.x + region.width, region.y + region.height))
        new_bbox = region.as_normalized_bbox(opened.width, opened.height)
        print_feature = feature_for_value(session, image=image, scope=SOURCE_PRINT, value=crop, region_seq=0, bbox_json=new_bbox)
    candidates.extend(retrieve(session, scope=SOURCE_PRINT, index_path=index_path(SOURCE_PRINT), query=_vector(print_feature), top_k=_task_setting(task, "retrieval_top_k", settings.retrieval_top_k), model_id=model_id, revision=revision, preprocess=preprocess, allowed_roles=("SOURCE_LIBRARY",), exclude_image_id=image.id))
    return _record_candidates(task, image, source, new_bbox, [candidate for candidate in candidates if candidate["score"] >= _task_setting(task, "retrieval_candidate_min_similarity", settings.retrieval_candidate_min_similarity)], session)


def deduplicate(task: Task, session: Session, thumbnails_dir: Path) -> None:
    if stop_if_cancelled(session, task):
        return
    batch = Path(task.source_batch_dir or "")
    source_library = Path(task.source_library_dir or "")
    if not batch.is_dir() or not source_library.is_dir():
        task.status = "FAILED"; task.warnings = [*task.warnings, "来源批次或历史图库不可访问，未执行来源去重"]; session.commit(); return
    historical = _historical_fingerprints(source_library)
    dry_run = bool(task.settings_snapshot.get("dry_run", False))
    try:
        catalog_source_library(session, source_library)
        session.commit()
        for scope in (SOURCE_FULL, SOURCE_PRINT):
            if stop_if_cancelled(session, task):
                return
            try:
                rebuild_scope_index(session, scope)
            except ValueError:
                pass
    except VisualUnavailableError as error:
        task.warnings = [*task.warnings, str(error)]
        session.commit()
    failures = deleted = processed = candidate_count = 0
    for source in sorted(batch.iterdir(), key=lambda entry: entry.name.casefold()):
        if stop_if_cancelled(session, task):
            return
        if not source.is_file() or source.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        try:
            snapshot = fingerprint(source)
        except OSError as error:
            failures += 1; add_event(session, task, "ERROR", "SCANNING", f"无法解码来源图：{source.name}：{error}"); session.commit(); continue
        image = Image(kind="SOURCE", original_filename=source.name, sha256=snapshot.sha256, pixel_digest=snapshot.pixel_digest, width=snapshot.width, height=snapshot.height, file_size=snapshot.size_bytes, status="PENDING")
        session.add(image); session.flush()
        item = TaskItem(task_id=task.id, image_id=image.id, observed_path=str(source), observed_path_digest=path_digest(source), stage="DECIDING", status="CHECKING", snapshot_sha256=snapshot.sha256, snapshot_size=snapshot.size_bytes, snapshot_mtime_ns=snapshot.mtime_ns)
        session.add(item); session.flush()
        if _is_exact_duplicate(snapshot, historical):
            if dry_run:
                item.status = "WOULD_DELETE"; processed += 1; session.commit(); continue
            operation = _operation(session, task, item, image, "DELETE", source, snapshot, "SOURCE_EXACT_DUPLICATE")
            try:
                operation.thumbnail_path = str(delete_verified(source, snapshot, thumbnails_dir / f"{operation.id}.jpg")); operation.state = "DONE"; item.status = "AUTO_DELETED"; image.status = "DELETED"; deleted += 1
            except Exception as error:
                operation.state = "FAILED"; operation.error_text = str(error); item.status = "ERROR"; failures += 1
        else:
            try:
                recorded, approved = _visual_candidates(task, image, source, session)
                candidate_count += recorded
                if approved and not dry_run:
                    operation = _operation(session, task, item, image, "DELETE", source, snapshot, "SOURCE_VISUAL_HIGH_CONFIRMED")
                    try:
                        operation.thumbnail_path = str(delete_verified(source, snapshot, thumbnails_dir / f"{operation.id}.jpg"))
                        operation.state = "DONE"; item.status = "AUTO_DELETED"; image.status = "DELETED"; approved.resolution_status = "AUTO_DELETED"; deleted += 1
                        processed += 1; session.commit(); continue
                    except Exception as error:
                        operation.state = "FAILED"; operation.error_text = str(error); item.status = "ERROR"; failures += 1
            except VisualUnavailableError as error:
                if str(error) not in task.warnings:
                    task.warnings = [*task.warnings, str(error)]
            except Exception as error:
                # Visual failures preserve the file; they are not a successful no-match.
                task.warnings = [*task.warnings, f"VISUAL_INDEX_FAILED:{source.name}:{error}"]
            if item.status == "CHECKING":
                item.status = "PASSED"
            historical.append(snapshot)
        processed += 1; session.commit()
    if stop_if_cancelled(session, task):
        return
    task.counters = {**task.counters, "processed": processed, "deleted": deleted, "visual_candidates": candidate_count, "errors": failures}
    task.status = "PARTIAL_COMPLETED" if failures else "DONE"
    add_event(session, task, "INFO", task.status, "来源精确去重完成；视觉候选已保留，未启用视觉自动删除")
    session.commit()
