import numpy as np

from app.indexing.faiss_store import FaissStore


def test_persistent_faiss_returns_nearest_vector(tmp_path) -> None:
    path = tmp_path / "pod.index"
    store = FaissStore(path, 3)
    store.add(np.array([10, 20]), np.array([[1, 0, 0], [0, 1, 0]], dtype=np.float32))
    assert path.exists()
    assert store.search(np.array([0.9, 0.1, 0], dtype=np.float32), 1)[0][0] == 10
    assert FaissStore(path, 3).search(np.array([0, 1, 0], dtype=np.float32), 1)[0][0] == 20
