"""铭牌号段规则：MP-0000 ~ MP-9999。

所有铭牌号在落库前一律经这里归一化与校验，
接口层不得直接信任网页或任何旁路传入的原始字符串。
"""
import re

PLATE_PREFIX = "MP"
PLATE_PATTERN = re.compile(r"^MP-\d{4}$")


def normalize_plate_no(raw) -> str:
    """去掉首尾空白与内部空白并转大写；非法形态留给 valid_plate_no 拒绝。"""
    if raw is None:
        return ""
    return re.sub(r"\s+", "", str(raw)).upper()


def valid_plate_no(no: str) -> bool:
    return bool(PLATE_PATTERN.match(no))
