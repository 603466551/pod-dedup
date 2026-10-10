import math
import re


DEFAULT_RATIO_CODES = ["1x1", "3x4", "4x3", "9x16", "16x9"]
_RATIO = re.compile(r"^\s*(\d{1,3})\s*[xX×:]\s*(\d{1,3})\s*$")


def normalize_ratio(value: str) -> str:
    match = _RATIO.match(value)
    if not match:
        raise ValueError("比例必须形如 1:1、2:3 或 2x3")
    width, height = int(match.group(1)), int(match.group(2))
    if width < 1 or height < 1:
        raise ValueError("比例的两个数必须大于零")
    divisor = math.gcd(width, height)
    return f"{width // divisor}x{height // divisor}"


def ratio_codes(values: list[str] | None) -> list[str]:
    normalized = [normalize_ratio(value) for value in values or DEFAULT_RATIO_CODES]
    return list(dict.fromkeys(normalized))
