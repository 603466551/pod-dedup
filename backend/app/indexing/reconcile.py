from pathlib import Path

import numpy as np
from sqlalchemy.orm import Session

from app.indexing.faiss_store import FaissStore
from app.indexing.feature_store import active_features


def rebuild_index(session: Session, *, scope: str, model_id: str, target: Path, revision: str | None = None, preprocess: str | None = None) -> FaissStore:
    features = active_features(session, scope=scope, model_id=model_id, revision=revision, preprocess=preprocess)
    if not features:
        raise ValueError("没有可用于重建索引的有效向量")
    dimensions = {feature.dimension for feature in features}
    if len(dimensions) != 1:
        raise ValueError("同一索引命名空间存在不同向量维度")
    store = FaissStore(target, dimensions.pop())
    vectors = np.vstack([np.frombuffer(feature.vector_blob, dtype="<f4") for feature in features])
    store.replace_all(np.array([feature.id for feature in features]), vectors)
    return store
