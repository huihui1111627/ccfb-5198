"""采集器基类与数据结构。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


class CollectorError(Exception):
    """采集失败（网络/解析/站点异常）。"""


class MarketClosed(Exception):
    """市场当日休市。"""

    def __init__(self, reason: str = "休市"):
        self.reason = reason
        super().__init__(reason)


@dataclass
class RawQuote:
    item_name: str
    raw_price: float
    raw_unit: str
    origin: str = ""
    grade: str = ""
    extra: dict = field(default_factory=dict)


class BaseCollector:
    """所有市场采集器的统一接口。"""

    def __init__(self, market_code: str, base_url: str):
        self.market_code = market_code
        self.base_url = base_url.rstrip("/")

    def open(self) -> None:  # 浏览器类采集器覆盖
        pass

    def close(self) -> None:
        pass

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    def fetch(self, d: date) -> list[RawQuote]:  # pragma: no cover - 接口定义
        raise NotImplementedError
