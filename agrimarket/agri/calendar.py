"""2026 年法定休市日 + 各市场额外休市安排。

法定节假日全市场休市；额外休市模拟单个市场因物流/盘点等原因闭市，
只在对应 mock 站生效，用来验证采集端对“非节假日闭市”的识别。
"""
from __future__ import annotations

from datetime import date


def _days(year: int, month: int, start: int, end: int) -> list[date]:
    return [date(year, month, d) for d in range(start, end + 1)]


# 法定节假日（2026 年安排）
_HOLIDAY_RANGES: list[tuple[str, list[date]]] = [
    ("元旦", _days(2026, 1, 1, 3)),
    ("春节", _days(2026, 2, 16, 22)),
    ("清明节", _days(2026, 4, 4, 6)),
    ("劳动节", _days(2026, 5, 1, 5)),
    ("端午节", _days(2026, 6, 19, 21)),
    ("中秋节", _days(2026, 9, 25, 27)),
    ("国庆节", _days(2026, 10, 1, 7)),
]

HOLIDAYS: dict[date, str] = {}
for _name, _ds in _HOLIDAY_RANGES:
    for _d in _ds:
        HOLIDAYS[_d] = _name


# 市场单独的额外休市日
EXTRA_CLOSURES: dict[str, list[date]] = {
    "A": [],
    "B": [date(2026, 10, 8)],                       # 国庆后勤盘点
    "C": [date(2026, 2, 14), date(2026, 2, 15), date(2026, 2, 23)],  # 春节物流停摆
}


def holiday_name(d: date) -> str | None:
    return HOLIDAYS.get(d)


def is_extra_closed(market_code: str, d: date) -> bool:
    return d in EXTRA_CLOSURES.get(market_code, [])
