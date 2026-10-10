from pathlib import Path


class PathValidationError(ValueError):
    pass


def canonical_path(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise PathValidationError("目录必须是执行端可访问的绝对路径")
    return path.resolve(strict=False)


def is_same_or_child(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def assert_distinct(left_label: str, left: str, right_label: str, right: str) -> None:
    left_path = canonical_path(left)
    right_path = canonical_path(right)
    if left_path == right_path:
        raise PathValidationError(f"{left_label}不能与{right_label}指向同一目录")


def validate_source_batch(source_batch_dir: str, source_library_dir: str) -> list[str]:
    batch = canonical_path(source_batch_dir)
    library = canonical_path(source_library_dir)
    if batch == library:
        raise PathValidationError("本次来源文件夹不能等于历史源图库根目录")
    if is_same_or_child(batch, library / "已处理"):
        raise PathValidationError("本次来源文件夹不能位于已处理目录内")
    if batch.parent == batch:
        raise PathValidationError("不能把磁盘根目录作为本次来源文件夹")
    return [] if batch.exists() else ["来源批次目录当前不存在；POD任务会按“无待整理来源”处理"]


def validate_pod_paths(pod_pending_dir: str, pod_library_dir: str) -> list[str]:
    pending = canonical_path(pod_pending_dir)
    library = canonical_path(pod_library_dir)
    if pending == library or is_same_or_child(pending, library):
        raise PathValidationError("POD待处理目录不能等于或位于POD图库内")
    if pending.parent == pending:
        raise PathValidationError("不能把磁盘根目录作为POD待处理目录")
    return [] if pending.exists() else ["POD待处理目录当前不存在"]

