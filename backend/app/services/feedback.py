"""Reuse human decisions only for the same unordered content-signature pair."""

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, aliased

from app.models.images import DuplicatePair, Image, Review


def reused_review(session: Session, *, new_sha256: bytes | None, match_image_id: int) -> dict | None:
    if new_sha256 is None:
        return None
    match = session.get(Image, match_image_id)
    if match is None or match.sha256 is None:
        return None
    first = aliased(Image)
    second = aliased(Image)
    row = session.execute(
        select(Review)
        .join(DuplicatePair, Review.pair_id == DuplicatePair.id)
        .join(first, DuplicatePair.image_new_id == first.id)
        .join(second, DuplicatePair.image_match_id == second.id)
        .where(
            Review.status == "RESOLVED",
            or_(
                (first.sha256 == new_sha256) & (second.sha256 == match.sha256),
                (first.sha256 == match.sha256) & (second.sha256 == new_sha256),
            ),
        )
        .order_by(Review.id.desc())
    ).scalars().first()
    if row is None:
        return None
    return {"review_id": row.id, "duplicate_decision": row.duplicate_decision, "action_decision": row.action_decision}
