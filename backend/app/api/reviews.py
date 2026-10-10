from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.enums import TaskStatus
from app.core.db import get_session
from app.models.images import DuplicatePair, FileOperation, Image, ImageFile, Review
from app.models.tasks import Task
from app.repositories.tasks import add_event
from app.services.pod_dedup import finalize_reviewed_task
from app.services.review_groups import PendingReviewLink, PendingReviewGroup, group_pending_review_links
from app.storage.fingerprint import fingerprint
from app.storage.safe_ops import delete_verified

router = APIRouter(prefix="/reviews", tags=["reviews"])


class ReviewDecision(BaseModel):
    duplicate_decision: str = Field(pattern="^(DUPLICATE|NOT_DUPLICATE|UNCERTAIN)$")
    action_decision: str = Field(pattern="^(DELETE_NEW|DELETE_MATCH|KEEP_BOTH|NONE)$")
    confirm_delete: bool = False
    note: str | None = Field(default=None, max_length=2000)
    version: int = Field(ge=1)


class GroupReviewDecision(BaseModel):
    decision: str = Field(pattern="^(DUPLICATE_KEEP_ALL|NOT_DUPLICATE_KEEP_ALL|DELETE_UNSELECTED)$")
    keep_image_ids: list[int] = Field(default_factory=list)
    confirm_delete: bool = False
    note: str | None = Field(default=None, max_length=2000)
    versions: dict[str, int] = Field(default_factory=dict)


def _report_unregistered_classified_copies(task: Task | None, files: list[ImageFile]) -> None:
    """Surface orphaned classified copies without ever deleting unregistered files."""
    if task is None or not task.pod_library_dir:
        return
    library = Path(task.pod_library_dir)
    if not library.is_dir():
        return
    registered = {str(Path(file.path).resolve(strict=False)).casefold() for file in files}
    missing = 0
    for file in files:
        if file.role != "POD_MASTER":
            continue
        master = Path(file.path)
        if master.parent.resolve(strict=False) != library.resolve(strict=False):
            continue
        for candidate in library.rglob(master.name):
            if candidate.is_file() and str(candidate.resolve(strict=False)).casefold() not in registered:
                missing += 1
    if missing:
        warning = f"UNREGISTERED_CLASSIFIED_COPY:{missing}"
        if warning not in task.warnings:
            task.warnings = [*task.warnings, warning]


def _pending_group_rows(session: Session, task_id: int | None = None) -> tuple[list[PendingReviewGroup], dict[int, tuple[Review, DuplicatePair]]]:
    statement = select(Review, DuplicatePair).join(DuplicatePair, Review.pair_id == DuplicatePair.id).where(Review.status == "PENDING")
    if task_id is not None:
        statement = statement.where(Review.task_id == task_id)
    rows = list(session.execute(statement))
    row_by_review_id = {review.id: (review, pair) for review, pair in rows}
    links = [
        PendingReviewLink(
            review_id=review.id,
            task_id=review.task_id,
            pair_id=pair.id,
            version=review.version,
            image_new_id=pair.image_new_id,
            image_match_id=pair.image_match_id,
        )
        for review, pair in rows
        if pair.image_match_id is not None
    ]
    return group_pending_review_links(links), row_by_review_id


def _image_payload(session: Session, image_id: int) -> dict[str, object]:
    image = session.get(Image, image_id)
    if image is None:
        return {"id": str(image_id), "filename": "图片记录缺失", "width": None, "height": None, "status": "MISSING"}
    return {"id": str(image.id), "filename": image.original_filename, "width": image.width, "height": image.height, "status": image.status}


def _group_payload(session: Session, group: PendingReviewGroup, row_by_review_id: dict[int, tuple[Review, DuplicatePair]]) -> dict[str, object]:
    return {
        "id": f"{group.task_id}:{group.seed_review_id}",
        "task_id": str(group.task_id),
        "seed_review_id": str(group.seed_review_id),
        "images": [_image_payload(session, image_id) for image_id in group.image_ids],
        "relations": [
            {
                "review_id": str(link.review_id),
                "pair_id": str(link.pair_id),
                "version": link.version,
                "new_image_id": str(link.image_new_id),
                "match_image_id": str(link.image_match_id),
                "machine_decision": row_by_review_id[link.review_id][1].machine_decision,
                "evidence": row_by_review_id[link.review_id][1].evidence_json,
            }
            for link in group.links
        ],
    }


def _delete_image_files(session: Session, task: Task, image_id: int, operation_prefix: str, reason: str) -> None:
    """Persist and verify every delete operation before removing a selected image."""
    files = list(session.scalars(select(ImageFile).where(ImageFile.image_id == image_id, ImageFile.file_status == "PRESENT")))
    if not files:
        raise HTTPException(409, detail={"code": "DELETE_TARGET_UNAVAILABLE", "message": "要删除的图片文件不存在或已删除", "details": {}})
    _report_unregistered_classified_copies(task, files)
    snapshots: list[tuple[ImageFile, Path, object]] = []
    missing_production_files = 0
    for file in files:
        path = Path(file.path)
        # Production crops are derived artifacts, never the original POD master.
        # If one was removed outside the system, record that fact but continue to
        # verify the master and every other registered file before deleting them.
        if file.role == "POD_PRODUCTION" and not path.is_file():
            file.file_status = "MISSING"
            missing_production_files += 1
            continue
        try:
            snapshots.append((file, path, fingerprint(path)))
        except OSError as error:
            raise HTTPException(409, detail={"code": "FILE_CHANGED", "message": "文件不可核验，请确认原图及归档副本仍存在", "details": {}}) from error

    if not snapshots:
        raise HTTPException(409, detail={"code": "DELETE_TARGET_UNAVAILABLE", "message": "要删除的原图文件不存在或已删除", "details": {}})
    if missing_production_files:
        add_event(session, task, "WARNING", "RECONCILE", f"已登记 {missing_production_files} 个缺失的生产裁切副本")

    operations: list[tuple[FileOperation, Path, object, ImageFile]] = []
    for file, path, snapshot in snapshots:
        operation = FileOperation(
            task_id=task.id,
            image_id=image_id,
            operation="DELETE",
            origin_path=str(path),
            origin_sha256=snapshot.sha256,
            expected_size=snapshot.size_bytes,
            operation_key=f"{operation_prefix}:delete:{file.id}",
            state="PREPARED",
            reason=reason,
        )
        session.add(operation)
        operations.append((operation, path, snapshot, file))
    session.commit()
    for operation, path, snapshot, file in operations:
        try:
            operation.thumbnail_path = str(delete_verified(path, snapshot, settings.data_dir / "thumbnails" / f"{operation.id}.jpg"))
            operation.state = "DONE"
            file.file_status = "DELETED"
        except Exception as error:
            operation.state = "FAILED"
            operation.error_text = str(error)
            session.commit()
            raise HTTPException(409, detail={"code": "FILE_CHANGED", "message": "文件在删除前发生变化", "details": {}}) from error
        session.commit()
    image = session.get(Image, image_id)
    if image:
        image.status = "DELETED"
    session.commit()


@router.get("")
def list_reviews(status: str = "PENDING", task_id: int | None = None, session: Session = Depends(get_session)):
    statement = select(Review).where(Review.status == status)
    if task_id is not None: statement = statement.where(Review.task_id == task_id)
    return {"items": [{"id": str(row.id), "task_id": str(row.task_id), "pair_id": str(row.pair_id), "status": row.status, "version": row.version} for row in session.scalars(statement)]}


@router.get("/groups")
def list_review_groups(task_id: int | None = None, session: Session = Depends(get_session)):
    """Return pending visual-review relations as connected image groups."""
    groups, rows = _pending_group_rows(session, task_id)
    return {
        "items": [_group_payload(session, group, rows) for group in groups],
        "pending_review_count": sum(len(group.links) for group in groups),
    }


@router.post("/{review_id}/group-decision")
def decide_group(review_id: int, payload: GroupReviewDecision, session: Session = Depends(get_session)):
    """Resolve a connected candidate group while retaining individual audit rows."""
    groups, rows = _pending_group_rows(session)
    group = next((candidate for candidate in groups if any(link.review_id == review_id for link in candidate.links)), None)
    if group is None:
        raise HTTPException(409, detail={"code": "REVIEW_GROUP_NOT_PENDING", "message": "该审核组已完成或已变化，请刷新列表", "details": {}})
    for link in group.links:
        expected_version = payload.versions.get(str(link.review_id))
        if expected_version != link.version:
            raise HTTPException(409, detail={"code": "REVIEW_VERSION_CONFLICT", "message": "审核组已被其它操作更新，请刷新后重试", "details": {}})

    image_ids = set(group.image_ids)
    keep_ids = set(payload.keep_image_ids)
    if not keep_ids.issubset(image_ids):
        raise HTTPException(422, detail={"code": "INVALID_KEEP_IMAGES", "message": "保留图片不属于当前审核组", "details": {}})
    task = session.get(Task, group.task_id)
    if task is None:
        raise HTTPException(404, detail={"code": "TASK_NOT_FOUND", "message": "审核所属任务不存在", "details": {}})
    if task.status in {TaskStatus.CANCEL_REQUESTED.value, TaskStatus.CANCELLED.value}:
        raise HTTPException(409, detail={"code": "TASK_CANCELLED", "message": "任务已取消，不能继续提交审核", "details": {}})

    delete_ids: set[int] = set()
    if payload.decision == "DELETE_UNSELECTED":
        if not keep_ids:
            raise HTTPException(422, detail={"code": "KEEP_IMAGE_REQUIRED", "message": "至少保留一张图片，不能删除整个审核组", "details": {}})
        delete_ids = image_ids - keep_ids
        if not delete_ids:
            raise HTTPException(422, detail={"code": "DELETE_IMAGE_REQUIRED", "message": "请取消至少一张图片的“保留”选择", "details": {}})
        if not payload.confirm_delete:
            raise HTTPException(422, detail={"code": "DELETE_CONFIRM_REQUIRED", "message": "永久删除必须二次确认", "details": {}})
        for image_id in sorted(delete_ids):
            _delete_image_files(session, task, image_id, f"review-group:{group.seed_review_id}", "HUMAN_REVIEW_GROUP")

    duplicate_decision = "NOT_DUPLICATE" if payload.decision == "NOT_DUPLICATE_KEEP_ALL" else "DUPLICATE"
    for link in group.links:
        review, pair = rows[link.review_id]
        review.duplicate_decision = duplicate_decision
        review.action_decision = "DELETE_GROUP_UNSELECTED" if ({link.image_new_id, link.image_match_id} & delete_ids) else "KEEP_BOTH"
        review.note = payload.note
        review.status = "RESOLVED"
        review.version += 1
        pair.resolution_status = "RESOLVED_BY_DELETION" if ({link.image_new_id, link.image_match_id} & delete_ids) else "RESOLVED"
    session.commit()
    add_event(session, task, "INFO", "REVIEW", f"候选审核组已完成：{len(group.image_ids)}张图片、{len(group.links)}条关系")
    session.commit()
    if task.type == "POD_DEDUP":
        finalize_reviewed_task(task, session, settings.data_dir / "thumbnails")
    return {"seed_review_id": str(group.seed_review_id), "resolved_reviews": len(group.links), "deleted_images": len(delete_ids)}


@router.get("/{review_id}")
def review_detail(review_id: int, session: Session = Depends(get_session)):
    review = session.get(Review, review_id)
    if review is None:
        raise HTTPException(404, detail={"code": "REVIEW_NOT_FOUND", "message": "审核不存在", "details": {}})
    pair = session.get(DuplicatePair, review.pair_id)
    if pair is None:
        raise HTTPException(404, detail={"code": "PAIR_NOT_FOUND", "message": "重复关系不存在", "details": {}})
    def image_payload(image_id: int | None):
        image = session.get(Image, image_id) if image_id else None
        if image is None:
            return None
        return {"id": str(image.id), "filename": image.original_filename, "width": image.width, "height": image.height, "status": image.status}
    return {"id": str(review.id), "task_id": str(review.task_id), "status": review.status, "version": review.version, "new_image": image_payload(pair.image_new_id), "match_image": image_payload(pair.image_match_id), "evidence": pair.evidence_json, "machine_decision": pair.machine_decision}


@router.post("/{review_id}/decision")
def decide(review_id: int, payload: ReviewDecision, session: Session = Depends(get_session)):
    review = session.get(Review, review_id)
    if review is None:
        raise HTTPException(404, detail={"code": "REVIEW_NOT_FOUND", "message": "审核不存在", "details": {}})
    if review.status != "PENDING":
        raise HTTPException(409, detail={"code": "REVIEW_NOT_PENDING", "message": "该审核已完成，页面将刷新最新列表", "details": {"status": review.status}})
    if review.version != payload.version:
        raise HTTPException(409, detail={"code": "REVIEW_VERSION_CONFLICT", "message": "审核已被其它操作更新，请刷新后重试", "details": {}})
    deleting = payload.action_decision in {"DELETE_NEW", "DELETE_MATCH"}
    if payload.duplicate_decision == "UNCERTAIN" and deleting:
        raise HTTPException(422, detail={"code": "UNCERTAIN_CANNOT_DELETE", "message": "暂不确定时不能删除文件", "details": {}})
    if deleting and not payload.confirm_delete:
        raise HTTPException(422, detail={"code": "DELETE_CONFIRM_REQUIRED", "message": "永久删除必须二次确认", "details": {}})
    pair = session.get(DuplicatePair, review.pair_id)
    if not pair: raise HTTPException(404, detail={"code": "PAIR_NOT_FOUND", "message": "重复关系不存在", "details": {}})
    task = session.get(Task, review.task_id)
    if task and task.status in {TaskStatus.CANCEL_REQUESTED.value, TaskStatus.CANCELLED.value}:
        raise HTTPException(409, detail={"code": "TASK_CANCELLED", "message": "任务已取消，不能继续提交审核", "details": {}})
    target_image_id = pair.image_new_id if payload.action_decision == "DELETE_NEW" else pair.image_match_id
    if deleting and target_image_id is None:
        raise HTTPException(409, detail={"code": "DELETE_TARGET_UNKNOWN", "message": "缺少可删除图片身份", "details": {}})
    if deleting:
        if task is None:
            raise HTTPException(404, detail={"code": "TASK_NOT_FOUND", "message": "审核所属任务不存在", "details": {}})
        _delete_image_files(session, task, target_image_id, f"review:{review.id}", "HUMAN_REVIEW")
    if payload.duplicate_decision == "UNCERTAIN":
        review.note = payload.note
        review.version += 1
        session.commit()
        return {"id": str(review.id), "status": review.status, "version": review.version}
    review.duplicate_decision = payload.duplicate_decision; review.action_decision = payload.action_decision; review.note = payload.note; review.status = "RESOLVED"; review.version += 1
    pair.resolution_status = "RESOLVED_BY_DELETION" if deleting else "RESOLVED"
    # When the newly submitted POD is deleted, all of its remaining candidate
    # relationships are no longer actionable.  Resolve them explicitly rather
    # than leaving hidden PENDING reviews that could keep the task locked.
    if deleting and payload.action_decision == "DELETE_NEW":
        related_pairs = list(session.scalars(select(DuplicatePair).where(DuplicatePair.image_new_id == target_image_id, DuplicatePair.id != pair.id)))
        for related_pair in related_pairs:
            related_pair.resolution_status = "RESOLVED_BY_DELETION"
            related_review = session.scalar(select(Review).where(Review.pair_id == related_pair.id, Review.status == "PENDING"))
            if related_review:
                related_review.duplicate_decision = "DUPLICATE"
                related_review.action_decision = "NONE"
                related_review.note = "新图已由另一条审核删除，关系自动结案"
                related_review.status = "RESOLVED"
                related_review.version += 1
    session.commit()
    task = session.get(Task, review.task_id)
    if task:
        add_event(session, task, "INFO", "REVIEW", "人工审核决定已记录")
        session.commit()
    if task and task.type == "POD_DEDUP":
        finalize_reviewed_task(task, session, settings.data_dir / "thumbnails")
    return {"id": str(review.id), "status": review.status, "version": review.version}
