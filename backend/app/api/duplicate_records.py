from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_session
from app.models.images import DuplicatePair, Image, Review

router = APIRouter(prefix="/duplicate-records", tags=["duplicate-records"])


@router.get("")
def list_duplicate_records(task_id: int | None = None, page: int = 1, session: Session = Depends(get_session)):
    statement = select(DuplicatePair).order_by(DuplicatePair.id.desc())
    if task_id is not None:
        statement = statement.where(DuplicatePair.task_id == task_id)
    rows = session.scalars(statement.offset((page - 1) * 50).limit(50))
    items = []
    for pair in rows:
        review = session.scalar(select(Review).where(Review.pair_id == pair.id))
        new_image = session.get(Image, pair.image_new_id)
        match_image = session.get(Image, pair.image_match_id) if pair.image_match_id else None
        items.append({
            "id": str(pair.id), "task_id": str(pair.task_id), "pair_type": pair.pair_type,
            "machine_decision": pair.machine_decision, "rule_id": pair.rule_id,
            "resolution_status": pair.resolution_status, "review_required": pair.review_required,
            "evidence": pair.evidence_json,
            "new_image": {"id": str(new_image.id), "filename": new_image.original_filename} if new_image else None,
            "match_image": {"id": str(match_image.id), "filename": match_image.original_filename} if match_image else None,
            "human_decision": {"status": review.status, "duplicate": review.duplicate_decision, "action": review.action_decision} if review else None,
        })
    return {"items": items, "page": page}
