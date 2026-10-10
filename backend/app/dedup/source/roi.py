"""A conservative, replaceable OpenCV source-print region locator."""

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


@dataclass(frozen=True)
class PrintRegion:
    x: int
    y: int
    width: int
    height: int
    confidence: float
    method: str = "opencv-content-region-v1"

    def as_normalized_bbox(self, image_width: int, image_height: int) -> dict:
        return {
            "x": self.x / image_width,
            "y": self.y / image_height,
            "width": self.width / image_width,
            "height": self.height / image_height,
            "confidence": self.confidence,
            "method": self.method,
        }


def locate_print_region(path: Path) -> PrintRegion | None:
    """Return an evidence-bearing content region, or None rather than guessing.

    This is not an object detector.  It accepts only a large, textured central
    region and deliberately falls back to whole-image retrieval for ambiguous
    photographs.
    """
    # cv2.imread() cannot reliably open non-ASCII Windows paths.  Reading the
    # bytes ourselves also keeps ROI retrieval available for Chinese filenames.
    try:
        encoded = np.fromfile(path, dtype=np.uint8)
        image = cv2.imdecode(encoded, cv2.IMREAD_COLOR) if encoded.size else None
    except (OSError, ValueError, cv2.error):
        return None
    if image is None:
        return None
    height, width = image.shape[:2]
    if width < 80 or height < 80:
        return None
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 60, 160)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9))
    mask = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=2)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    total = width * height
    candidates: list[tuple[float, tuple[int, int, int, int]]] = []
    for contour in contours:
        x, y, box_width, box_height = cv2.boundingRect(contour)
        area_ratio = (box_width * box_height) / total
        if not 0.12 <= area_ratio <= 0.82:
            continue
        center_distance = abs((x + box_width / 2) / width - 0.5) + abs((y + box_height / 2) / height - 0.5)
        if center_distance > 0.42:
            continue
        edge_density = float(edges[y:y + box_height, x:x + box_width].mean() / 255.0)
        if edge_density < 0.01:
            continue
        candidates.append((area_ratio * edge_density * (1 - center_distance), (x, y, box_width, box_height)))
    if not candidates:
        return None
    score, (x, y, box_width, box_height) = max(candidates, key=lambda candidate: candidate[0])
    # The score is only diagnostic; the strict gates above establish usability.
    return PrintRegion(x, y, box_width, box_height, min(0.99, score * 8))
