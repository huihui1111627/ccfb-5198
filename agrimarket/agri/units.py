"""单位归一：斤 / 公斤 / 箱 / 件 统一换算成 元每公斤。

设计要点（这是本系统最在意的部分）：
- 斤、公斤是固定换算，硬规则；
- 箱、件没有统一规格，必须按「市场 + 品种」配置包装净重（package_specs 表），
  采集时逐品种查规格，绝不按一个常数一刀切；
- 缺规格时抛 MissingPackageSpec，由采集编排层登记 unmapped/告警，绝不瞎猜。
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

JIN_PER_KG = 2.0


class MissingPackageSpec(Exception):
    """箱/件价格缺少按品种配置的包装规格。"""

    def __init__(self, market_code: str, variety_code: str, pack_unit: str):
        self.market_code = market_code
        self.variety_code = variety_code
        self.pack_unit = pack_unit
        super().__init__(
            f"缺少包装规格: 市场={market_code} 品种={variety_code} 单位={pack_unit}，"
            f"请先在设置/映射页配置每{pack_unit}净重(公斤)"
        )


@dataclass
class NormalizedPrice:
    price_per_kg: float
    basis: str  # 换算依据说明，落库后可追溯


def _parse_unit(raw_unit: str) -> tuple[str, str]:
    """'元/公斤' -> ('元','公斤')；兼容 '元/箱'、'元/件'、'元/斤'。"""
    u = raw_unit.strip().replace(" ", "")
    if "/" in u:
        _, per = u.split("/", 1)
    else:
        per = u
    per = per.replace("千克", "公斤").replace("kg", "公斤").replace("KG", "公斤")
    return "元", per


def get_package_spec(
    conn: sqlite3.Connection, market_code: str, variety_code: str, pack_unit: str
) -> float:
    row = conn.execute(
        "SELECT spec_kg FROM package_specs WHERE market_code=? AND variety_code=?",
        (market_code, variety_code),
    ).fetchone()
    if not row or not row["spec_kg"] or row["spec_kg"] <= 0:
        raise MissingPackageSpec(market_code, variety_code, pack_unit)
    return float(row["spec_kg"])


def normalize(
    raw_price: float,
    raw_unit: str,
    *,
    conn: sqlite3.Connection,
    market_code: str,
    variety_code: str,
) -> NormalizedPrice:
    """把任意原始单位的单价换算为 元/公斤。"""
    _, per = _parse_unit(raw_unit)

    if per == "公斤":
        return NormalizedPrice(round(float(raw_price), 4), "公斤直读")
    if per == "斤":
        return NormalizedPrice(
            round(float(raw_price) * JIN_PER_KG, 4),
            f"{raw_price} 元/斤 × {JIN_PER_KG:g} 斤/公斤",
        )
    if per in ("箱", "件"):
        spec_kg = get_package_spec(conn, market_code, variety_code, per)
        return NormalizedPrice(
            round(float(raw_price) / spec_kg, 4),
            f"{raw_price} 元/{per} ÷ {spec_kg:g} 公斤/{per}（按{market_code}市场{variety_code}规格）",
        )
    raise ValueError(f"暂不支持的计价单位: {raw_unit!r}")
