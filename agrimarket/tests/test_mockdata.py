"""mock 数据：确定性、休市、单位口径、突变埋点。"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from agri.mockdata import (MARKET_C_PACKING, is_open, kg_price,
                           quotes_for)


def test_deterministic_same_input_same_output(an_open_day):
    a = quotes_for("A", an_open_day)
    b = quotes_for("A", an_open_day)
    assert [q.to_dict() for q in a] == [q.to_dict() for q in b]


def test_three_markets_share_same_kg_price(an_open_day):
    """三个站口径不同，但各自换算回 元/公斤 后应与源公斤价一致（市场有档位系数，互不同价）。"""
    for q in quotes_for("A", an_open_day):
        assert q.raw_price == pytest.approx(kg_price("A", an_open_day, q.variety), abs=0.01)
    for q in quotes_for("B", an_open_day):  # 1 公斤 = 2 斤
        assert q.raw_price * 2 == pytest.approx(kg_price("B", an_open_day, q.variety), abs=0.02)
    for q in quotes_for("C", an_open_day):
        spec_kg = MARKET_C_PACKING[q.variety][1]
        assert q.raw_price / spec_kg == pytest.approx(
            kg_price("C", an_open_day, q.variety), abs=0.02
        )


def test_market_b_uses_jin(an_open_day):
    assert all(q.raw_unit == "元/斤" for q in quotes_for("B", an_open_day))


def test_market_c_uses_packing_units(an_open_day):
    units = {q.variety: q.raw_unit for q in quotes_for("C", an_open_day)}
    assert units["苹果"] == "元/箱"
    assert units["大白菜"] == "元/件"


def test_holiday_closed_for_all(holiday_day):
    assert all(not is_open(c, holiday_day) for c in ("A", "B", "C"))
    assert all(quotes_for(c, holiday_day) == [] for c in ("A", "B", "C"))


def test_extra_closure_per_market():
    # B 市场 10-08 单独闭市，A 正常
    assert not is_open("B", date(2026, 10, 8))
    assert is_open("A", date(2026, 10, 8))


def test_window_has_continuous_output():
    """整个数据窗口内开市日都有行情产出。"""
    start = date(2026, 9, 1)
    open_days_with_data = 0
    for offset in range(74):
        d = start + timedelta(days=offset)
        if is_open("A", d):
            assert len(quotes_for("A", d)) == 10
            open_days_with_data += 1
    assert open_days_with_data > 30
