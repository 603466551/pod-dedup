import hashlib
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps


@dataclass(frozen=True)
class Fingerprint:
    path: Path
    sha256: bytes
    pixel_digest: bytes
    width: int
    height: int
    size_bytes: int
    mtime_ns: int


def path_digest(path: Path) -> bytes:
    return hashlib.sha256(str(path.resolve(strict=False)).replace("/", "\\").casefold().encode()).digest()


def fingerprint(path: Path) -> Fingerprint:
    stat = path.stat()
    content = hashlib.sha256(path.read_bytes()).digest()
    with Image.open(path) as image:
        normalized = ImageOps.exif_transpose(image).convert("RGBA")
        pixels = normalized.tobytes()
        digest = hashlib.sha256(f"{normalized.width}x{normalized.height}:RGBA".encode() + pixels).digest()
        return Fingerprint(path, content, digest, normalized.width, normalized.height, stat.st_size, stat.st_mtime_ns)


def verify_snapshot(path: Path, snapshot: Fingerprint) -> bool:
    if not path.is_file():
        return False
    try:
        current = fingerprint(path)
    except (OSError, ValueError):
        return False
    return current.sha256 == snapshot.sha256 and current.size_bytes == snapshot.size_bytes and current.mtime_ns == snapshot.mtime_ns
