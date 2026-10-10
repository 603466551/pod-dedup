from pathlib import Path

from PIL import Image

from app.dedup.source.roi import locate_print_region


def test_locate_print_region_accepts_windows_unicode_filename(tmp_path: Path) -> None:
    path = tmp_path / "中文图像.png"
    image = Image.new("RGB", (240, 240), "white")
    for x in range(60, 180):
        for y in range(60, 180):
            image.putpixel((x, y), (x % 255, y % 255, 80))
    image.save(path)

    # The exact ROI is intentionally conservative, but a readable image must
    # never fail solely because its Windows path contains Chinese characters.
    assert locate_print_region(path) is not None
