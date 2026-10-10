"""FAISS retrieval with MySQL and filesystem validity checks."""

from pathlib import Path

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.indexing.faiss_store import FaissStore
from app.models.images import ImageFeature, ImageFile


def retrieve(session: Session, *, scope: str, index_path: Path, query: np.ndarray, top_k: int, model_id: str, revision: str, preprocess: str, allowed_roles: tuple[str, ...], exclude_image_id: int | None = None) -> list[dict]:
    features = {
        feature.id: feature
        for feature in session.scalars(select(ImageFeature).where(
            ImageFeature.feature_scope == scope,
            ImageFeature.model_id == model_id,
            ImageFeature.model_revision == revision,
            ImageFeature.preprocess_version == preprocess,
            ImageFeature.is_valid.is_(True),
        ))
    }
    if not features:
        return []
    dimension = next(iter(features.values())).dimension
    results = FaissStore(index_path, dimension).search(query, top_k)
    candidates: list[dict] = []
    for feature_id, score in results:
        feature = features.get(feature_id)
        if feature is None or feature.image_id == exclude_image_id:
            continue
        file = session.scalar(select(ImageFile).where(ImageFile.image_id == feature.image_id, ImageFile.role.in_(allowed_roles), ImageFile.file_status == "PRESENT"))
        if file and Path(file.path).is_file():
            candidates.append({"image_id": feature.image_id, "feature_id": feature.id, "score": score, "path": file.path, "scope": scope, "bbox": feature.bbox_json, "ratio_code": file.ratio_code})
    return candidates
