import numpy as np
from sqlalchemy.orm import Session

from pathlib import Path

from app.dedup.common.retriever import retrieve


def pod_candidates(session: Session, *, index_path: Path, query: np.ndarray, top_k: int, model_id: str, revision: str, preprocess: str, exclude_image_id: int | None = None) -> list[dict]:
    candidates = retrieve(session, scope="POD_FULL", index_path=index_path, query=query, top_k=top_k, model_id=model_id, revision=revision, preprocess=preprocess, allowed_roles=("POD_MASTER", "POD_PENDING"), exclude_image_id=exclude_image_id)
    return candidates
