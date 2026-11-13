"""Mock 行情数据生成（三个市场共用同一份确定性数据源）。

关键设计：
- 以 (市场, 日期, 品种) 做哈希种子，任意时刻、任意进程重新生成结果完全一致，
  Excel 站、表格站、JS 变量站拿到的是同一份数；
- 价格围绕基准价做季节性+周波动+噪声，另埋约 3% 的突变样本供异常检测命中；
- 不同市场用自己的品名、单位和档位，制造“品名乱、单位乱”的真实感。
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import date, timedelta

from .calendar import holiday_name, is_extra_closed
from .config import WINDOW_START

# ---------------------------------------------------------------- 品种主数据
# code -> (标准品名, 品类, 基准价 元/公斤)
VARIETIES: dict[str, tuple[str, str, float]] = {
    "大白菜": ("大白菜", "叶菜类", 1.6),
    "黄瓜": ("黄瓜", "瓜果类", 4.2),
    "西红柿": ("西红柿", "茄果类", 5.0),
    "土豆": ("土豆", "根茎类", 2.6),
    "白萝卜": ("白萝卜", "根茎类", 1.8),
    "胡萝卜": ("胡萝卜", "根茎类", 3.2),
    "茄子": ("茄子", "茄果类", 4.8),
    "辣椒": ("辣椒", "茄果类", 7.5),
    "苹果": ("苹果", "水果类", 8.5),
    "香蕉": ("香蕉", "水果类", 5.5),
}

ORIGINS = ["山东寿光", "云南昆明", "海南三亚", "河北张北", "陕西洛川", "广西南宁", "甘肃定西", "本地"]
GRADES = ["一级", "二级", "统货"]

# 各市场自己的“土名字” -> 标准品种
MARKET_ITEM_NAMES: dict[str, dict[str, str]] = {
    "A": {
        "大白菜": "大白菜", "黄瓜": "黄瓜", "西红柿": "番茄", "土豆": "马铃薯",
        "白萝卜": "白萝卜", "胡萝卜": "胡萝卜", "茄子": "茄子", "辣椒": "青椒",
        "苹果": "红富士苹果", "香蕉": "香蕉",
    },
    "B": {
        "大白菜": "黄芽白", "黄瓜": "青瓜", "西红柿": "西红柿", "土豆": "洋芋",
        "白萝卜": "长白萝卜", "胡萝卜": "甘荀", "茄子": "矮瓜", "辣椒": "线椒",
        "苹果": "苹果", "香蕉": "蕉果",
    },
    "C": {
        "大白菜": "结球白菜", "西红柿": "番茄", "土豆": "土豆",
        "茄子": "紫长茄", "苹果": "红富士", "香蕉": "海南香蕉",
    },
}

# 各市场实际经营的品种
MARKET_SKUS: dict[str, list[str]] = {
    "A": list(VARIETIES.keys()),
    "B": ["大白菜", "黄瓜", "西红柿", "土豆", "白萝卜", "胡萝卜", "茄子", "辣椒", "苹果", "香蕉"],
    "C": ["大白菜", "西红柿", "土豆", "茄子", "苹果", "香蕉"],
}

# 市场档位系数
MARKET_MULTIPLIER: dict[str, float] = {"A": 1.0, "B": 1.08, "C": 0.95}

# C 市场按包装卖：单位 + 单包规格(公斤)。箱/件规格按品种配置，不是一刀切
MARKET_C_PACKING: dict[str, tuple[str, float]] = {
    "大白菜": ("件", 20.0),
    "西红柿": ("箱", 10.0),
    "土豆": ("件", 25.0),
    "茄子": ("箱", 8.0),
    "苹果": ("箱", 15.0),
    "香蕉": ("件", 12.0),
}

# 单位
MARKET_UNIT_PRICE: dict[str, str] = {"A": "元/公斤", "B": "元/斤", "C": ""}  # C 的单位逐品种取


def _seeded_rng(*parts: object) -> float:
    """返回 [0,1) 稳定伪随机数。"""
    raw = "|".join(str(p) for p in parts).encode()
    h = hashlib.sha256(raw).digest()
    return int.from_bytes(h[:8], "big") / 2**64


@dataclass
class MockQuote:
    variety: str          # 标准品种 code
    item_name: str        # 市场原始品名
    raw_price: float      # 市场原始单位下的价格
    raw_unit: str         # 原始单位（元/公斤、元/斤、元/箱、元/件）
    origin: str
    grade: str

    def to_dict(self) -> dict:
        return {
            "variety": self.variety,
            "item_name": self.item_name,
            "raw_price": round(self.raw_price, 2),
            "raw_unit": self.raw_unit,
            "origin": self.origin,
            "grade": self.grade,
        }


def is_open(market_code: str, d: date) -> bool:
    """当天是否开市：法定节假日全休，外加市场自身闭市日。"""
    if holiday_name(d) is not None:
        return False
    if is_extra_closed(market_code, d):
        return False
    if d < WINDOW_START or d > date.today():
        return False
    return True


def day_index(d: date) -> int:
    return (d - WINDOW_START).days


def _stable_int(*parts: object, mod: int = 7) -> int:
    """跨进程稳定的整数哈希（不能用内置 hash()，它受 PYTHONHASHSEED 影响）。"""
    raw = "|".join(str(p) for p in parts).encode()
    return int.from_bytes(hashlib.sha256(raw).digest()[:4], "big") % mod


def kg_price(market_code: str, d: date, variety: str) -> float:
    """确定性生成 元/公斤 口径的真实价（含季节性波动与埋点突变）。"""
    base = VARIETIES[variety][2] * MARKET_MULTIPLIER[market_code]
    idx = day_index(d)
    seasonal = 1.0 + 0.12 * math.sin(idx / 14.0 + _stable_int(variety, "phase"))
    weekly = 1.0 + 0.03 * ((d.weekday() - 2) / 3.0)
    noise = 1.0 + (_seeded_rng(market_code, d.isoformat(), variety, "noise") - 0.5) * 0.08
    price = base * seasonal * weekly * noise

    # 突变埋点：约 3% 概率出现 +35%~+70% 的跳价或 -30%~-50% 的跳水
    shock_roll = _seeded_rng(market_code, d.isoformat(), variety, "shock")
    if shock_roll < 0.03:
        if shock_roll < 0.02:
            price *= 1.35 + _seeded_rng(market_code, d.isoformat(), variety, "up") * 0.35
        else:
            price *= 0.5 + _seeded_rng(market_code, d.isoformat(), variety, "down") * 0.2
    return round(price, 2)


def quotes_for(market_code: str, d: date) -> list[MockQuote]:
    """生成某市场某天的原始行情（休市返回空列表）。"""
    if not is_open(market_code, d):
        return []
    out: list[MockQuote] = []
    for variety in MARKET_SKUS[market_code]:
        per_kg = kg_price(market_code, d, variety)
        origin = ORIGINS[int(_seeded_rng(market_code, d.isoformat(), variety, "origin") * len(ORIGINS))]
        grade = GRADES[int(_seeded_rng(market_code, d.isoformat(), variety, "grade") * len(GRADES))]
        if market_code == "A":
            raw_price, raw_unit = per_kg, "元/公斤"
        elif market_code == "B":
            raw_price, raw_unit = round(per_kg / 2, 2), "元/斤"  # 1 公斤 = 2 斤
        else:
            pack_unit, spec_kg = MARKET_C_PACKING[variety]
            raw_price, raw_unit = round(per_kg * spec_kg, 2), f"元/{pack_unit}"
        out.append(
            MockQuote(
                variety=variety,
                item_name=MARKET_ITEM_NAMES[market_code][variety],
                raw_price=raw_price,
                raw_unit=raw_unit,
                origin=origin,
                grade=grade,
            )
        )
    return out


def open_days(market_code: str, start: date, end: date) -> list[date]:
    cur, days = start, []
    while cur <= end:
        if is_open(market_code, cur):
            days.append(cur)
        cur += timedelta(days=1)
    return days
