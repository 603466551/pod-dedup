from PIL import Image

from app.dedup.common.embedding import LocalDinoV2Embedder


def test_local_dinov2_extracts_384_dimensions(tmp_path) -> None:
    image_path = tmp_path / "fixture.png"
    Image.new("RGB", (32, 32), "red").save(image_path)
    vector = LocalDinoV2Embedder().embed(image_path)
    assert vector.shape == (384,)
