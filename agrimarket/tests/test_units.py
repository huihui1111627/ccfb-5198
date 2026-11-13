"""单位换算：斤/公斤固定换算，箱/件按品种规格，缺规格必须报错。"""
from __future__ import annotations

import pytest

from agri.db import get_conn
from agri.units import MissingPackageSpec, normalize


def test_kg_direct(db_path):
    with get_conn(db_path) as conn:
        r = normalize(3.5, "元/公斤", conn=conn, market_code="A", variety_code="黄瓜")
    assert r.price_per_kg == 3.5
    assert "公斤" in r.basis


def test_jin_to_kg(db_path):
    with get_conn(db_path) as conn:
        r = normalize(2.5, "元/斤", conn=conn, market_code="B", variety_code="黄瓜")
    assert r.price_per_kg == 5.0  # 1 公斤 = 2 斤


def test_box_uses_variety_spec(db_path):
    # C 市场苹果：每箱 15 公斤，整箱 127.5 元 -> 8.5 元/公斤
    with get_conn(db_path) as conn:
        r = normalize(127.5, "元/箱", conn=conn, market_code="C", variety_code="苹果")
    assert r.price_per_kg == pytest.approx(8.5)
    assert "15" in r.basis


def test_piece_uses_another_variety_spec(db_path):
    # C 市场大白菜：每件 20 公斤，整件 32 元 -> 1.6 元/公斤
    with get_conn(db_path) as conn:
        r = normalize(32.0, "元/件", conn=conn, market_code="C", variety_code="大白菜")
    assert r.price_per_kg == pytest.approx(1.6)


def test_specs_are_per_variety_not_one_size_fits_all(db_path):
    """箱和件规格必须逐品种不同，验证没有一刀切。"""
    with get_conn(db_path) as conn:
        specs = {
            r["variety_code"]: r["spec_kg"]
            for r in conn.execute(
                "SELECT variety_code, spec_kg FROM package_specs WHERE market_code='C'"
            ).fetchall()
        }
    assert len(set(specs.values())) > 1  # 至少存在两种不同规格


def test_missing_spec_raises(db_path):
    with get_conn(db_path) as conn:
        with pytest.raises(MissingPackageSpec) as exc:
            normalize(60.0, "元/箱", conn=conn, market_code="A", variety_code="黄瓜")
    assert "黄瓜" in str(exc.value)


def test_unsupported_unit(db_path):
    with get_conn(db_path) as conn:
        with pytest.raises(ValueError):
            normalize(1.0, "元/箩筐", conn=conn, market_code="A", variety_code="黄瓜")
