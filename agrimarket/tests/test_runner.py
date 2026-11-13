"""采集编排端到端：映射->换算->落库->异常，补采与休市跳过。"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from agri.config import today
from agri.db import get_conn
from agri.services.runner import backfill, collect_all, run_market_day


def test_full_pipeline_all_markets(mock_servers, db_path, an_open_day, monkeypatch):
    monkeypatch.setenv("AGRI_TODAY", an_open_day.isoformat())
    results = collect_all(an_open_day, db_path)
    status = {r.market_code: r for r in results}
    assert status["A"].status == "success"
    assert status["B"].status == "success"
    assert status["C"].status == "success"
    # A/B 各 10 个品种，C 6 个
    assert status["A"].saved == 10
    assert status["B"].saved == 10
    assert status["C"].saved == 6

    with get_conn(db_path) as conn:
        # B 市场档位系数 1.08，归一到 元/公斤 后应约为 A 的 1.08 倍（噪声同口径）
        row_a = conn.execute(
            "SELECT price_per_kg FROM quotes WHERE market_code='A' AND quote_date=? AND variety_code='大白菜'",
            (an_open_day.isoformat(),),
        ).fetchone()
        row_b = conn.execute(
            "SELECT price_per_kg FROM quotes WHERE market_code='B' AND quote_date=? AND variety_code='大白菜'",
            (an_open_day.isoformat(),),
        ).fetchone()
        assert row_b["price_per_kg"] == pytest.approx(
            row_a["price_per_kg"] * 1.08, rel=0.03
        )

        # C 市场箱价换算回公斤后与 mock 源一致
        row_c = conn.execute(
            "SELECT price_per_kg, raw_price, raw_unit FROM quotes "
            "WHERE market_code='C' AND quote_date=? AND variety_code='苹果'",
            (an_open_day.isoformat(),),
        ).fetchone()
        assert row_c["raw_unit"] == "元/箱"
        assert row_c["price_per_kg"] == round(row_c["raw_price"] / 15, 4)


def test_closed_day_recorded(mock_servers, db_path, holiday_day):
    r = run_market_day("A", holiday_day, db_path)
    assert r.status == "closed"
    with get_conn(db_path) as conn:
        run = conn.execute(
            "SELECT * FROM collection_runs WHERE market_code='A' AND quote_date=?",
            (holiday_day.isoformat(),),
        ).fetchone()
        assert run["status"] == "closed"
        assert run["closed_reason"]
        assert conn.execute("SELECT COUNT(*) c FROM quotes").fetchone()["c"] == 0


def test_backfill_skips_done_and_closed(mock_servers, db_path, monkeypatch):
    fixed_today = date(2026, 11, 13)
    monkeypatch.setenv("AGRI_TODAY", fixed_today.isoformat())
    first = backfill("A", days=45, db_path=db_path)
    # 窗口内包含国庆休市日，应有 closed 记录
    assert any(r.status == "closed" for r in first)
    assert any(r.status == "success" for r in first)

    with get_conn(db_path) as conn:
        success_dates = {
            r["quote_date"] for r in conn.execute(
                "SELECT DISTINCT quote_date FROM collection_runs WHERE market_code='A' AND status='success'"
            ).fetchall()
        }

    # 再跑一次默认补采：成功日不重复
    second = backfill("A", days=45, db_path=db_path)
    second_dates = {r.quote_date for r in second if r.status == "success"}
    assert second_dates.isdisjoint(success_dates)

    # force 模式会重采
    forced = backfill("A", days=5, db_path=db_path, force=True)
    assert any(r.status == "success" for r in forced)


def test_backfill_all_markets_covers_window(mock_servers, db_path, monkeypatch):
    monkeypatch.setenv("AGRI_TODAY", "2026-11-13")
    backfill(days=73, db_path=db_path)  # 覆盖 9/1 起整个 mock 窗口
    with get_conn(db_path) as conn:
        total = conn.execute("SELECT COUNT(*) c FROM quotes").fetchone()["c"]
        # 三个市场 70+ 开市日，必然是上千条
        assert total > 800
        # 窗口内埋点突变应已被异常检测捕获
        pending = conn.execute(
            "SELECT COUNT(*) c FROM anomalies WHERE status='pending'"
        ).fetchone()["c"]
        assert pending > 0


def test_missing_package_spec_is_quarantined(mock_servers, db_path, an_open_day):
    """删掉 C 市场苹果的箱规后采集：该品种不入库，进未映射清单且 run 标记缺规格。"""
    with get_conn(db_path) as conn:
        conn.execute("DELETE FROM package_specs WHERE market_code='C' AND variety_code='苹果'")
    r = run_market_day("C", an_open_day, db_path)
    assert r.missing_spec == 1
    assert r.saved == 5  # 其余 5 个品种正常
    with get_conn(db_path) as conn:
        hit = conn.execute(
            "SELECT * FROM unmapped_quotes WHERE market_code='C' AND raw_name='红富士'"
        ).fetchone()
        assert hit is not None
        assert "苹果" not in [
            row["variety_code"] for row in conn.execute(
                "SELECT variety_code FROM quotes WHERE market_code='C' AND quote_date=?",
                (an_open_day.isoformat(),),
            ).fetchall()
        ]
