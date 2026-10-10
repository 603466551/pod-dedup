import numpy as np
import pytest

from app.indexing.feature_store import normalized_blob


def test_normalized_blob_is_stable_and_unit_length() -> None:
    blob, checksum = normalized_blob(np.array([3, 4], dtype=np.float32))
    assert len(checksum) == 32
    assert np.isclose(np.linalg.norm(np.frombuffer(blob, dtype="<f4")), 1.0)


def test_zero_vector_is_rejected() -> None:
    with pytest.raises(ValueError, match="零向量"):
        normalized_blob(np.zeros(3, dtype=np.float32))
