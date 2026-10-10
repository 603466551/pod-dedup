from pathlib import Path
from datetime import datetime

import pytest
from PIL import Image

from app.storage.fingerprint import fingerprint
from app.storage.safe_ops import FileChangedError, copy_verified, crop_center_verified, delete_verified, move_verified, plan_target, timestamped_filename


def image(path: Path, color: str) -> Path:
    Image.new("RGB", (8, 8), color).save(path)
    return path


def test_move_avoids_same_name_collision(tmp_path: Path) -> None:
    source = image(tmp_path / "source.png", "red")
    destination = tmp_path / "library"
    image(destination.mkdir() or destination / "source.png", "blue")
    moved = move_verified(source, destination, fingerprint(source))
    assert moved.name == "source_1.png"
    assert moved.exists() and not source.exists()


def test_copy_and_delete_recheck_identity(tmp_path: Path) -> None:
    source = image(tmp_path / "source.png", "red")
    snapshot = fingerprint(source)
    copied = copy_verified(source, tmp_path / "classified", "final.png", snapshot)
    assert copied.exists() and source.exists()
    source.write_bytes(b"changed")
    with pytest.raises(FileChangedError):
        delete_verified(source, snapshot, tmp_path / "thumb.jpg")


def test_timestamped_filename_preserves_extension_and_collision_uses_suffix(tmp_path: Path) -> None:
    source = image(tmp_path / "external name (2).PNG", "red")
    name = timestamped_filename(source, datetime(2026, 10, 8, 11, 22, 3, 854000))
    assert name == "20261008112203854.PNG"
    destination = tmp_path / "library"; destination.mkdir()
    image(destination / name, "blue")
    assert plan_target(destination, name, fingerprint(source)).name == "20261008112203854_1.PNG"


def test_center_crop_creates_production_image_without_changing_master(tmp_path: Path) -> None:
    source = tmp_path / "master.png"
    Image.new("RGB", (8, 6), "red").save(source)
    snapshot = fingerprint(source)
    cropped = crop_center_verified(source, tmp_path / "Production" / "1x1" / "261008", source.name, snapshot, 1, 1)
    assert source.exists() and fingerprint(source).sha256 == snapshot.sha256
    with Image.open(cropped) as result:
        assert result.size == (6, 6)
