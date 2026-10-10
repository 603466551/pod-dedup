from pathlib import Path

import pytest

from app.storage.paths import PathValidationError, validate_pod_paths, validate_source_batch


def test_source_batch_must_not_be_library(tmp_path: Path) -> None:
    with pytest.raises(PathValidationError, match="不能等于"):
        validate_source_batch(str(tmp_path), str(tmp_path))


def test_source_batch_cannot_be_processed_child(tmp_path: Path) -> None:
    library = tmp_path / "library"
    processed = library / "已处理" / "nested"
    with pytest.raises(PathValidationError, match="已处理"):
        validate_source_batch(str(processed), str(library))


def test_pod_pending_cannot_be_inside_library(tmp_path: Path) -> None:
    library = tmp_path / "pod-library"
    with pytest.raises(PathValidationError, match="POD待处理"):
        validate_pod_paths(str(library / "Portrait"), str(library))


def test_missing_source_batch_is_warning_not_pod_blocker(tmp_path: Path) -> None:
    warnings = validate_source_batch(str(tmp_path / "missing"), str(tmp_path / "library"))
    assert warnings == ["来源批次目录当前不存在；POD任务会按“无待整理来源”处理"]

