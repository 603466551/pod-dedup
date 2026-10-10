"""MySQL-backed POD feature catalog; FAISS remains a rebuildable cache."""

from collections.abc import Callable
from pathlib import Path

import numpy as np
from PIL import Image as PillowImage
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.dedup.common.embedding import LocalDinoV2Embedder, VisualUnavailableError
from app.dedup.source.roi import locate_print_region
from app.indexing.feature_store import save_feature
from app.indexing.reconcile import rebuild_index
from app.models.images import Image, ImageFeature, ImageFile
from app.storage.fingerprint import fingerprint, path_digest

SCOPE = "POD_FULL"
SOURCE_FULL = "SOURCE_FULL"
SOURCE_PRINT = "SOURCE_PRINT"
_embedder = LocalDinoV2Embedder()


def pod_index_path() -> Path:
    return index_path(SCOPE)


def index_path(scope: str) -> Path:
    return settings.data_dir / "faiss" / scope / "facebook_dinov2_vits14.index"


def feature_for_path(session: Session, *, image: Image, path: Path) -> ImageFeature:
    return feature_for_value(session, image=image, scope=SCOPE, value=path)


def feature_for_value(session: Session, *, image: Image, scope: str, value: Path | PillowImage.Image, region_seq: int = 0, bbox_json: dict | None = None) -> ImageFeature:
    existing = session.scalar(
        select(ImageFeature).where(
            ImageFeature.image_id == image.id,
            ImageFeature.feature_scope == scope,
            ImageFeature.model_id == _embedder.model_id,
            ImageFeature.model_revision == _embedder.model_revision,
            ImageFeature.preprocess_version == _embedder.preprocess_version,
            ImageFeature.region_seq == region_seq,
            ImageFeature.is_valid.is_(True),
        )
    )
    if existing:
        return existing
    return save_feature(
        session,
        image_id=image.id,
        scope=scope,
        model_id=_embedder.model_id,
        revision=_embedder.model_revision,
        preprocess=_embedder.preprocess_version,
        vector=_embedder.embed(value) if isinstance(value, Path) else _embedder.embed_image(value),
        region_seq=region_seq,
        bbox_json=bbox_json,
    )


def register_library_master(session: Session, path: Path) -> Image:
    normalized = path_digest(path)
    file = session.scalar(select(ImageFile).where(ImageFile.normalized_path_digest == normalized))
    if file:
        image = session.get(Image, file.image_id)
        if image is None:
            raise RuntimeError("POD主文件登记缺少图片身份")
        return image
    snapshot = fingerprint(path)
    image = Image(kind="POD", original_filename=path.name, sha256=snapshot.sha256, pixel_digest=snapshot.pixel_digest, width=snapshot.width, height=snapshot.height, file_size=snapshot.size_bytes, status="LIBRARY")
    session.add(image)
    session.flush()
    session.add(ImageFile(image_id=image.id, role="POD_MASTER", path=str(path), normalized_path_digest=normalized, size_bytes=snapshot.size_bytes, mtime_ns=snapshot.mtime_ns, sha256=snapshot.sha256, file_status="PRESENT"))
    return image


def register_source_library(session: Session, path: Path) -> Image:
    normalized = path_digest(path)
    file = session.scalar(select(ImageFile).where(ImageFile.normalized_path_digest == normalized))
    if file:
        image = session.get(Image, file.image_id)
        if image is None:
            raise RuntimeError("来源图库文件登记缺少图片身份")
        return image
    snapshot = fingerprint(path)
    image = Image(kind="SOURCE", original_filename=path.name, sha256=snapshot.sha256, pixel_digest=snapshot.pixel_digest, width=snapshot.width, height=snapshot.height, file_size=snapshot.size_bytes, status="LIBRARY")
    session.add(image); session.flush()
    session.add(ImageFile(image_id=image.id, role="SOURCE_LIBRARY", path=str(path), normalized_path_digest=normalized, size_bytes=snapshot.size_bytes, mtime_ns=snapshot.mtime_ns, sha256=snapshot.sha256, file_status="PRESENT"))
    return image


def catalog_library(session: Session, library: Path, progress: Callable[[int], None] | None = None) -> int:
    """Register and index flat POD masters only; classified copies are excluded."""
    indexed = 0
    for path in sorted(library.iterdir(), key=lambda entry: entry.name.casefold()):
        if not path.is_file() or path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}:
            continue
        image = register_library_master(session, path)
        feature_for_path(session, image=image, path=path)
        indexed += 1
        if progress:
            progress(indexed)
    return indexed


def catalog_source_library(session: Session, library: Path) -> tuple[int, int]:
    """Index source full images and only conservatively located print regions."""
    full_count = print_count = 0
    for path in sorted(library.iterdir(), key=lambda entry: entry.name.casefold()):
        if not path.is_file() or path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}:
            continue
        image = register_source_library(session, path)
        feature_for_value(session, image=image, scope=SOURCE_FULL, value=path)
        full_count += 1
        region = locate_print_region(path)
        if region is None:
            continue
        with PillowImage.open(path) as source:
            crop = source.convert("RGB").crop((region.x, region.y, region.x + region.width, region.y + region.height))
            feature_for_value(session, image=image, scope=SOURCE_PRINT, value=crop, region_seq=0, bbox_json=region.as_normalized_bbox(source.width, source.height))
        print_count += 1
    return full_count, print_count


def rebuild_pod_index(session: Session):
    return rebuild_scope_index(session, SCOPE)


def rebuild_scope_index(session: Session, scope: str):
    return rebuild_index(
        session,
        scope=scope,
        model_id=_embedder.model_id,
        revision=_embedder.model_revision,
        preprocess=_embedder.preprocess_version,
        target=index_path(scope),
    )


def query_vector(path: Path) -> np.ndarray:
    return _embedder.embed(path)


def model_namespace() -> tuple[str, str, str]:
    return _embedder.model_id, _embedder.model_revision, _embedder.preprocess_version
