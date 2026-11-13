"""三个真实采集器对 mock 站的端到端采集（含 Playwright 浏览器用例）。"""
from __future__ import annotations

from datetime import date

import pytest

from agri.collectors.base import MarketClosed
from agri.collectors.market_a import MarketACollector
from agri.collectors.market_b import MarketBCollector
from agri.collectors.market_c import MarketCCollector


def test_market_a_paginated_table(mock_servers, an_open_day):
    url = f"http://127.0.0.1:{mock_servers['A']}"
    with MarketACollector("A", url) as c:
        rows = c.fetch(an_open_day)
    assert len(rows) == 10            # 每页 5 条，翻页拿全
    assert all(r.raw_unit == "元/公斤" for r in rows)
    assert any(r.item_name == "番茄" for r in rows)   # A 市场自己的品名


def test_market_a_closed_day(mock_servers, holiday_day):
    url = f"http://127.0.0.1:{mock_servers['A']}"
    with MarketACollector("A", url) as c:
        with pytest.raises(MarketClosed):
            c.fetch(holiday_day)


def test_market_b_requires_browser(mock_servers, an_open_day, browser_available):
    if not browser_available:
        pytest.skip("本机 Playwright 浏览器不可用")
    url = f"http://127.0.0.1:{mock_servers['B']}"
    with MarketBCollector("B", url) as c:
        rows = c.fetch(an_open_day)
    assert len(rows) == 10
    assert all(r.raw_unit == "元/斤" for r in rows)
    assert any(r.item_name == "黄芽白" for r in rows)  # 黄芽白 = 大白菜


def test_market_b_closed_day(mock_servers, holiday_day, browser_available):
    if not browser_available:
        pytest.skip("本机 Playwright 浏览器不可用")
    url = f"http://127.0.0.1:{mock_servers['B']}"
    with MarketBCollector("B", url) as c:
        with pytest.raises(MarketClosed):
            c.fetch(holiday_day)


def test_market_c_excel(mock_servers, an_open_day):
    url = f"http://127.0.0.1:{mock_servers['C']}"
    with MarketCCollector("C", url) as c:
        rows = c.fetch(an_open_day)
    assert len(rows) == 6
    units = {r.item_name: r.raw_unit for r in rows}
    assert any("元/箱" in u for u in units.values())
    assert any("元/件" in u for u in units.values())
    # Excel 包装列被带进 extra，供溯源
    assert all(r.extra.get("packing") for r in rows)


def test_market_c_closed_404(mock_servers, holiday_day):
    url = f"http://127.0.0.1:{mock_servers['C']}"
    with MarketCCollector("C", url) as c:
        with pytest.raises(MarketClosed):
            c.fetch(holiday_day)
