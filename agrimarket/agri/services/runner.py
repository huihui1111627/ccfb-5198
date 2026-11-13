"""采集编排：把原始行情经过 映射 -> 单位归一 -> 落库 -> 异常检测 串起来。

对外主入口：
- run_market_day(market_code, d)      单市场单日
- collect_all(d)                      全市场单日（定时任务调它）
- backfill(market_code, days)         漏采补采，自动跳过休市日与已成功日期
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta

from ..collectors.base import CollectorError, MarketClosed
from ..collectors.factory import build_collector
from ..config import today
from ..db import get_conn
from ..mockdata import is_open
from ..units import MissingPackageSpec, normalize
from . import mapping
from .anomaly import evaluate_quote


@dataclass
class DayResult:
    market_code: str
    quote_date: str
    status: str                 # success / closed / failed
    fetched: int = 0
    saved: int = 0
    unmapped: int = 0
    missing_spec: int = 0
    message: str = ""


def _record_run(conn: sqlite3.Connection, r: DayResult, closed_reason: str | None = None) -> None:
    conn.execute(
        "INSERT INTO collection_runs(market_code,quote_date,status,fetched_count,"
        "saved_count,closed_reason,message,finished_at) VALUES(?,?,?,?,?,?,?,datetime('now','localtime'))",
        (r.market_code, r.quote_date, r.status, r.fetched, r.saved,
         closed_reason, r.message),
    )


def _upsert_quote(conn: sqlite3.Connection, market_code: str, d: date,
                  raw, variety_code: str, price_per_kg: float) -> sqlite3.Row:
    conn.execute(
        "INSERT INTO quotes(market_code,quote_date,variety_code,raw_name,raw_price,"
        "raw_unit,price_per_kg,origin,grade) VALUES(?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(market_code,quote_date,variety_code) DO UPDATE SET "
        "raw_name=excluded.raw_name, raw_price=excluded.raw_price, raw_unit=excluded.raw_unit, "
        "price_per_kg=excluded.price_per_kg, origin=excluded.origin, grade=excluded.grade, "
        "collected_at=datetime('now','localtime')",
        (market_code, d.isoformat(), variety_code, raw.item_name, raw.raw_price,
         raw.raw_unit, price_per_kg, raw.origin, raw.grade),
    )
    return conn.execute(
        "SELECT * FROM quotes WHERE market_code=? AND quote_date=? AND variety_code=?",
        (market_code, d.isoformat(), variety_code),
    ).fetchone()


def run_market_day(market_code: str, d: date, db_path: str | None = None) -> DayResult:
    result = DayResult(market_code, d.isoformat(), "failed")
    with get_conn(db_path) as conn:
        market = conn.execute("SELECT * FROM markets WHERE code=?", (market_code,)).fetchone()
        if not market:
            result.message = f"市场 {market_code} 不存在"
            _record_run(conn, result)
            return result
        if not market["enabled"]:
            result.status = "failed"
            result.message = "市场已停用"
            _record_run(conn, result)
            return result

        # 休市预判（法定节假日 + 市场额外闭市）
        if not is_open(market_code, d):
            result.status = "closed"
            result.message = "休市跳过"
            _record_run(conn, result, closed_reason="节假日/市场休市")
            return result

        collector = build_collector(market["source_type"], market_code, market["base_url"])
        try:
            collector.open()
            try:
                raws = collector.fetch(d)
            finally:
                collector.close()
        except MarketClosed as exc:
            result.status = "closed"
            result.message = str(exc)
            _record_run(conn, result, closed_reason=exc.reason)
            return result
        except CollectorError as exc:
            result.message = str(exc)
            _record_run(conn, result)
            return result

        result.fetched = len(raws)
        for raw in raws:
            variety_code = mapping.resolve_variety(conn, market_code, raw.item_name)
            if not variety_code:
                mapping.register_unmapped(conn, market_code, raw.item_name, raw.raw_unit)
                result.unmapped += 1
                continue
            try:
                normalized = normalize(
                    raw.raw_price, raw.raw_unit,
                    conn=conn, market_code=market_code, variety_code=variety_code,
                )
            except MissingPackageSpec as exc:
                # 缺箱/件规格：登记未映射队列备注，等配置后补采，不猜规格
                mapping.register_unmapped(conn, market_code, raw.item_name, raw.raw_unit)
                result.missing_spec += 1
                result.message = (result.message + "; " if result.message else "") + str(exc)
                continue

            row = _upsert_quote(conn, market_code, d, raw, variety_code,
                                normalized.price_per_kg)
            evaluate_quote(conn, row)
            result.saved += 1

        result.status = "success" if result.saved else "failed"
        if not result.message:
            result.message = (
                f"采集 {result.fetched} 条，入库 {result.saved} 条"
                + (f"，未识别 {result.unmapped} 条" if result.unmapped else "")
                + (f"，缺包装规格 {result.missing_spec} 条" if result.missing_spec else "")
            )
        _record_run(conn, result)
        return result


def collect_all(d: date | None = None, db_path: str | None = None) -> list[DayResult]:
    d = d or today()
    with get_conn(db_path) as conn:
        markets = conn.execute("SELECT code FROM markets WHERE enabled=1 ORDER BY code").fetchall()
    return [run_market_day(m["code"], d, db_path) for m in markets]


def _last_success_date(conn: sqlite3.Connection, market_code: str) -> str | None:
    row = conn.execute(
        "SELECT quote_date FROM collection_runs WHERE market_code=? AND status='success' "
        "ORDER BY quote_date DESC LIMIT 1",
        (market_code,),
    ).fetchone()
    return row["quote_date"] if row else None


def backfill(market_code: str | None = None, days: int = 15,
             db_path: str | None = None, force: bool = False) -> list[DayResult]:
    """补采过去 N 天。默认跳过已成功的日期，force=True 则重采。"""
    end = today()
    start = end - timedelta(days=days)
    results: list[DayResult] = []
    with get_conn(db_path) as conn:
        if market_code:
            codes = [r["code"] for r in conn.execute(
                "SELECT code FROM markets WHERE code=? AND enabled=1", (market_code,)).fetchall()]
        else:
            codes = [r["code"] for r in conn.execute(
                "SELECT code FROM markets WHERE enabled=1 ORDER BY code").fetchall()]

    for code in codes:
        cur = start
        while cur <= end:
            if not force:
                with get_conn(db_path) as check_conn:
                    done = check_conn.execute(
                        "SELECT 1 FROM collection_runs WHERE market_code=? AND quote_date=? "
                        "AND status='success' LIMIT 1",
                        (code, cur.isoformat()),
                    ).fetchone()
            else:
                done = None
            if not done:
                results.append(run_market_day(code, cur, db_path))
            cur += timedelta(days=1)
    return results


def list_runs(conn: sqlite3.Connection, limit: int = 100) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT r.*, m.name AS market_name FROM collection_runs r "
        "JOIN markets m ON m.code=r.market_code "
        "ORDER BY r.quote_date DESC, r.market_code, r.id DESC LIMIT ?",
        (limit,),
    ).fetchall()
