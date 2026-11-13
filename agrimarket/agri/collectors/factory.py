"""按市场 source_type 实例化采集器。"""
from __future__ import annotations

from .base import BaseCollector
from .market_a import MarketACollector
from .market_b import MarketBCollector
from .market_c import MarketCCollector

_REGISTRY = {
    "table": MarketACollector,
    "jsvar": MarketBCollector,
    "excel": MarketCCollector,
}


def build_collector(source_type: str, market_code: str, base_url: str) -> BaseCollector:
    cls = _REGISTRY.get(source_type)
    if cls is None:
        raise ValueError(f"未知采集类型: {source_type}")
    return cls(market_code, base_url)
