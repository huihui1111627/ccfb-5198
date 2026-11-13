"""seed 幂等性：重复初始化不能复活用户删除的运营数据。"""
from __future__ import annotations

from agri.db import get_conn
from agri.seed import seed


def test_seed_does_not_resurrect_deleted_alias(db_path):
    with get_conn(db_path) as conn:
        conn.execute(
            "DELETE FROM variety_aliases WHERE market_code='B' AND raw_name='黄芽白'"
        )
        deleted = conn.execute(
            "SELECT COUNT(*) c FROM variety_aliases WHERE market_code='B' AND raw_name='黄芽白'"
        ).fetchone()["c"]
    assert deleted == 0

    # 再次初始化（不带 force），删除的映射不应回来
    assert seed(db_path) is False
    with get_conn(db_path) as conn:
        assert conn.execute(
            "SELECT COUNT(*) c FROM variety_aliases WHERE market_code='B' AND raw_name='黄芽白'"
        ).fetchone()["c"] == 0
        # 主数据仍在
        assert conn.execute("SELECT COUNT(*) c FROM markets").fetchone()["c"] == 3
        assert conn.execute("SELECT COUNT(*) c FROM varieties").fetchone()["c"] == 10


def test_seed_force_rebuilds(db_path):
    with get_conn(db_path) as conn:
        conn.execute(
            "DELETE FROM variety_aliases WHERE market_code='B' AND raw_name='黄芽白'"
        )
    assert seed(db_path, force=True) is True
    with get_conn(db_path) as conn:
        assert conn.execute(
            "SELECT COUNT(*) c FROM variety_aliases WHERE market_code='B' AND raw_name='黄芽白'"
        ).fetchone()["c"] == 1


def test_seed_keeps_user_deleted_holiday(db_path):
    with get_conn(db_path) as conn:
        conn.execute("DELETE FROM holidays WHERE d='2026-10-01'")
    seed(db_path)
    with get_conn(db_path) as conn:
        assert conn.execute(
            "SELECT 1 FROM holidays WHERE d='2026-10-01'"
        ).fetchone() is None
