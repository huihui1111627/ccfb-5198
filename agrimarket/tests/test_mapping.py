"""品种映射：别名归一、未识别登记、补齐映射。"""
from __future__ import annotations

from agri.db import get_conn
from agri.services import mapping


def test_alias_resolution(db_path):
    with get_conn(db_path) as conn:
        # 黄芽白(B 市场的叫法) 应归一到 大白菜
        assert mapping.resolve_variety(conn, "B", "黄芽白") == "大白菜"
        assert mapping.resolve_variety(conn, "A", "马铃薯") == "土豆"
        assert mapping.resolve_variety(conn, "A", "不存在的菜") is None


def test_unmapped_register_and_resolve(db_path):
    with get_conn(db_path) as conn:
        mapping.register_unmapped(conn, "A", "太空番茄", "元/公斤")
        mapping.register_unmapped(conn, "A", "太空番茄", "元/公斤")  # 命中累计
        rows = mapping.list_unmapped(conn)
        hit = [r for r in rows if r["raw_name"] == "太空番茄"][0]
        assert hit["hit_count"] == 2

        mapping.add_alias(conn, "A", "太空番茄", "西红柿")
        assert mapping.resolve_variety(conn, "A", "太空番茄") == "西红柿"
        # 补齐后待处理清单移除
        assert not [r for r in mapping.list_unmapped(conn) if r["raw_name"] == "太空番茄"]


def test_alias_delete_then_unmapped_again(db_path):
    with get_conn(db_path) as conn:
        alias_id = conn.execute(
            "SELECT id FROM variety_aliases WHERE market_code='B' AND raw_name='黄芽白'"
        ).fetchone()["id"]
        mapping.delete_alias(conn, alias_id)
        assert mapping.resolve_variety(conn, "B", "黄芽白") is None
