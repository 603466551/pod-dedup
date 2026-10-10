"""Independent local correspondence evidence for high-confidence source rules."""

from pathlib import Path

import cv2
import numpy as np


def _crop(image, bbox: dict | None):
    if not bbox:
        return image
    height, width = image.shape[:2]
    x = max(0, min(width - 1, int(bbox["x"] * width)))
    y = max(0, min(height - 1, int(bbox["y"] * height)))
    right = max(x + 1, min(width, int((bbox["x"] + bbox["width"]) * width)))
    bottom = max(y + 1, min(height, int((bbox["y"] + bbox["height"]) * height)))
    return image[y:bottom, x:right]


def verify_print_correspondence(new_path: Path, match_path: Path, new_bbox: dict | None = None, match_bbox: dict | None = None) -> dict:
    """Return ORB correspondence evidence; never infer a match from embeddings."""
    new = cv2.imread(str(new_path), cv2.IMREAD_GRAYSCALE)
    old = cv2.imread(str(match_path), cv2.IMREAD_GRAYSCALE)
    if new is None or old is None:
        return {"valid": False, "reason": "image_unreadable"}
    new, old = _crop(new, new_bbox), _crop(old, match_bbox)
    detector = cv2.ORB_create(nfeatures=1200, fastThreshold=10)
    new_points, new_descriptors = detector.detectAndCompute(new, None)
    old_points, old_descriptors = detector.detectAndCompute(old, None)
    if new_descriptors is None or old_descriptors is None:
        return {"valid": False, "reason": "insufficient_features"}
    pairs = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(new_descriptors, old_descriptors, k=2)
    good = [first for first, second in pairs if first.distance < 0.72 * second.distance]
    if len(good) < 18:
        return {"valid": False, "reason": "too_few_ratio_matches", "good_matches": len(good)}
    source = np.float32([new_points[match.queryIdx].pt for match in good]).reshape(-1, 1, 2)
    target = np.float32([old_points[match.trainIdx].pt for match in good]).reshape(-1, 1, 2)
    _, mask = cv2.findHomography(source, target, cv2.RANSAC, 4.0)
    inliers = int(mask.sum()) if mask is not None else 0
    return {"valid": inliers >= 14 and inliers / len(good) >= 0.55, "good_matches": len(good), "inliers": inliers, "inlier_ratio": inliers / len(good), "method": "orb-ransac-v1"}
