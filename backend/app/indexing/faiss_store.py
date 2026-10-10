"""Persistent FAISS caches; MySQL feature rows remain the source of truth."""

from pathlib import Path

import faiss
import numpy as np


class FaissStore:
    def __init__(self, path: Path, dimension: int) -> None:
        self.path = path
        self.dimension = dimension
        self.index = self._load_or_create()

    def _load_or_create(self):
        if self.path.exists():
            index = faiss.read_index(str(self.path))
            if index.d != self.dimension:
                raise ValueError("FAISS索引维度与当前模型不一致，必须重建")
            return index
        return faiss.IndexIDMap2(faiss.IndexFlatIP(self.dimension))

    def add(self, ids: np.ndarray, vectors: np.ndarray) -> None:
        ids = np.asarray(ids, dtype=np.int64)
        vectors = np.asarray(vectors, dtype=np.float32)
        if vectors.ndim != 2 or vectors.shape[1] != self.dimension or len(ids) != len(vectors):
            raise ValueError("FAISS向量或ID维度不合法")
        faiss.normalize_L2(vectors)
        self.index.add_with_ids(vectors, ids)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        faiss.write_index(self.index, str(temporary))
        temporary.replace(self.path)

    def replace_all(self, ids: np.ndarray, vectors: np.ndarray) -> None:
        """Atomically rebuild the cache from persisted MySQL vectors."""
        ids = np.asarray(ids, dtype=np.int64)
        vectors = np.asarray(vectors, dtype=np.float32)
        if vectors.ndim != 2 or vectors.shape[1] != self.dimension or len(ids) != len(vectors):
            raise ValueError("FAISS向量或ID维度不合法")
        replacement = faiss.IndexIDMap2(faiss.IndexFlatIP(self.dimension))
        faiss.normalize_L2(vectors)
        replacement.add_with_ids(vectors, ids)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        faiss.write_index(replacement, str(temporary))
        temporary.replace(self.path)
        self.index = replacement

    def search(self, vector: np.ndarray, top_k: int) -> list[tuple[int, float]]:
        query = np.asarray(vector, dtype=np.float32).reshape(1, -1)
        if query.shape[1] != self.dimension:
            raise ValueError("查询向量维度不合法")
        faiss.normalize_L2(query)
        scores, ids = self.index.search(query, top_k)
        return [(int(identifier), float(score)) for identifier, score in zip(ids[0], scores[0]) if identifier != -1]
