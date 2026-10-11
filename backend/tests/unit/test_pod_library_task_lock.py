from pathlib import Path

from app.core.enums import TaskType
from app.services.tasks import _resource_keys, _same_pod_library


def test_pod_dedup_and_crop_share_a_library_lock(tmp_path: Path) -> None:
    pending = tmp_path / "pending"
    library = tmp_path / "library"
    pending.mkdir()
    library.mkdir()

    dedup_keys = _resource_keys(
        TaskType.POD_DEDUP,
        {"pod_pending_dir": str(pending), "pod_library_dir": str(library)},
    )
    crop_keys = _resource_keys(
        TaskType.POD_CROP,
        {"pod_library_dir": str(library), "ratio_code": "1x1"},
    )

    assert set(dedup_keys) & set(crop_keys)


def test_pod_library_comparison_normalizes_equivalent_paths(tmp_path: Path) -> None:
    library = tmp_path / "library"
    library.mkdir()

    assert _same_pod_library(str(library), str(tmp_path / "." / "library"))
