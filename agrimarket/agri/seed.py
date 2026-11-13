"""初始化数据库与基础数据：市场、品种、别名、包装规格、设置、节假日。"""
from __future__ import annotations

from .calendar import HOLIDAYS
from .config import market_url
from .db import get_conn, init_db, set_setting
from .mockdata import MARKET_C_PACKING, MARKET_ITEM_NAMES, MARKET_SKUS, VARIETIES

MARKETS = [
    ("A", "华东果菜批发市场", "table", "分页 HTML 表格（元/公斤）"),
    ("B", "城南农贸批发市场", "jsvar", "JS 变量渲染（元/斤）"),
    ("C", "北环批发市场", "excel", "每日 Excel 报价单（箱/件）"),
]

DEFAULT_SETTINGS = {
    "anomaly_pct": "30",          # 环比突变阈值(%)
    "scheduler_enabled": "1",
    "scheduler_hour": "18",       # 每天定时采集时刻
    "scheduler_minute": "0",
    "backfill_days": "15",        # 补采默认回看天数
    "page_size": "20",
}


def seed(db_path: str | None = None, *, force: bool = False) -> bool:
    """初始化数据库与基础数据。

    库已经初始化过（markets 表有数据）时直接跳过，保证用户在控制台做的
    别名删除、规格调整、休市日维护不会被后续 CLI 调用悄悄种回来。
    需要显式重建时传 force=True，或用 `agri init --force`。
    返回本次是否真正执行了初始化。
    """
    init_db(db_path)
    with get_conn(db_path) as conn:
        if not force and conn.execute("SELECT COUNT(*) c FROM markets").fetchone()["c"] > 0:
            return False

        # 市场
        for code, name, stype, desc in MARKETS:
            conn.execute(
                "INSERT INTO markets(code,name,source_type,base_url) VALUES(?,?,?,?) "
                "ON CONFLICT(code) DO UPDATE SET name=excluded.name, "
                "source_type=excluded.source_type, base_url=excluded.base_url",
                (code, name, stype, market_url(code)),
            )

        # 标准品种
        for code, (name, category, base_price) in VARIETIES.items():
            conn.execute(
                "INSERT INTO varieties(code,name,category,base_price) VALUES(?,?,?,?) "
                "ON CONFLICT(code) DO UPDATE SET name=excluded.name, "
                "category=excluded.category, base_price=excluded.base_price",
                (code, name, category, base_price),
            )

        # 各市场原始品名 -> 标准品种 的别名映射
        # 只在缺失时插入：用户在控制台删除/调整过的映射不会被重新种回来
        for market_code, mapping in MARKET_ITEM_NAMES.items():
            for variety, raw_name in mapping.items():
                conn.execute(
                    "INSERT OR IGNORE INTO variety_aliases(market_code,raw_name,variety_code) "
                    "VALUES(?,?,?)",
                    (market_code, raw_name, variety),
                )

        # C 市场箱/件规格（按品种，不一刀切）；同上，已被用户改动/删除的不覆盖
        for variety, (pack_unit, spec_kg) in MARKET_C_PACKING.items():
            conn.execute(
                "INSERT OR IGNORE INTO package_specs(market_code,variety_code,pack_unit,spec_kg) "
                "VALUES(?,?,?,?)",
                ("C", variety, pack_unit, spec_kg),
            )

        # 节假日：内置日历只补缺，用户自行删除/新增的记录保持原样
        for d, name in HOLIDAYS.items():
            conn.execute(
                "INSERT OR IGNORE INTO holidays(d,name) VALUES(?,?)",
                (d.isoformat(), name),
            )

        # 设置（已存在的不覆盖，保留用户改动）
        for key, value in DEFAULT_SETTINGS.items():
            exists = conn.execute("SELECT 1 FROM settings WHERE key=?", (key,)).fetchone()
            if not exists:
                set_setting(conn, key, value)
    return True
