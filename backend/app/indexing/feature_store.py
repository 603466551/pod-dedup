import hashlib

import numpy as np
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.images import ImageFeature


def normalized_blob(vector: np.ndarray) -> tuple[bytes, bytes]:
    values = np.asarray(vector, dtype=np.float32).reshape(-1)
    norm = np.linalg.norm(values)
    if norm == 0:
        raise ValueError("特征向量不能为零向量")
    values = values / norm
    blob = values.astype("<f4", copy=False).tobytes()
    return blob, hashlib.sha256(blob).digest()


def save_feature(session: Session, *, image_id: int, scope: str, model_id: str, revision: str, preprocess: str, vector: np.ndarray, region_seq: int = 0, bbox_json: dict | None = None) -> ImageFeature:
    blob, checksum = normalized_blob(vector)
    session.execute(
        update(ImageFeature)
        .where(
            ImageFeature.image_id == image_id,
            ImageFeature.feature_scope == scope,
            ImageFeature.model_id == model_id,
            ImageFeature.model_revision == revision,
            ImageFeature.preprocess_version == preprocess,
            ImageFeature.region_seq == region_seq,
            ImageFeature.is_valid.is_(True),
        )
        .values(is_valid=False)
    )
    feature = ImageFeature(image_id=image_id, feature_scope=scope, region_seq=region_seq, bbox_json=bbox_json, model_id=model_id, model_revision=revision, preprocess_version=preprocess, dimension=len(vector), vector_blob=blob, vector_sha256=checksum, is_valid=True)
    session.add(feature); session.flush()
    feature.faiss_vector_id = feature.id
    return feature


def active_features(session: Session, *, scope: str, model_id: str, revision: str | None = None, preprocess: str | None = None) -> list[ImageFeature]:
    statement = select(ImageFeature).where(ImageFeature.feature_scope == scope, ImageFeature.model_id == model_id, ImageFeature.is_valid.is_(True))
    if revision is not None:
        statement = statement.where(ImageFeature.model_revision == revision)
    if preprocess is not None:
        statement = statement.where(ImageFeature.preprocess_version == preprocess)
    return list(session.scalars(statement))
