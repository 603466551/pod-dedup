import pytest
from pathlib import Path

from app.services.pod_crop import canonical_master_date, production_filename
from app.services.ratios import normalize_ratio, ratio_codes


def test_custom_ratio_normalization_and_deduplication() -> None:
    assert normalize_ratio(" 4:6 ") == "2x3"
    assert ratio_codes(["1:1", "2x3", "4:6"]) == ["1x1", "2x3"]
    with pytest.raises(ValueError):
        normalize_ratio("square")


def test_production_filename_marks_its_ratio() -> None:
    assert production_filename(Path("20261008112203854.png"), "1x1") == "20261008112203854_1x1.png"


def test_canonical_master_date_uses_the_full_calendar_date() -> None:
    assert canonical_master_date(Path("20261008112203854.png")) == "20261008"
    assert canonical_master_date(Path("20261008112203854_1.png")) == "20261008"
    assert canonical_master_date(Path("custom-name.png")) is None
