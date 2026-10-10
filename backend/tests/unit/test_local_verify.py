import numpy as np
from PIL import Image

from app.dedup.source.local_verify import verify_print_correspondence


def test_orb_local_correspondence_requires_real_feature_matches(tmp_path) -> None:
    values = np.zeros((300, 300, 3), dtype=np.uint8)
    for y in range(20, 280, 30):
        for x in range(20, 280, 30):
            values[y:y + 12, x:x + 12] = ((x * 7) % 255, (y * 11) % 255, ((x + y) * 3) % 255)
    first, second = tmp_path / "first.png", tmp_path / "second.png"
    Image.fromarray(values).save(first)
    Image.fromarray(values).save(second)
    result = verify_print_correspondence(first, second)
    assert result["valid"] and result["inliers"] >= 14
