"""走势与市场对比查询。"""
from __future__ import annotations

import sqlite3


def trend(conn: sqlite3.Connection, variety_code: str, start: str, end: str,
          market_code: str | None = None) -> list[dict]:
    """某品种区间内按日期的行情（可限市场），用于走势图。"""
    sql = (
        "SELECT q.quote_date, q.market_code, m.name AS market_name, q.price_per_kg "
        "FROM quotes q JOIN markets m ON m.code=q.market_code "
        "WHERE q.variety_code=? AND q.quote_date BETWEEN ? AND ?"
    )
    params: list = [variety_code, start, end]
    if market_code:
        sql += " AND q.market_code=?"
        params.append(market_code)
    sql += " ORDER BY q.quote_date, q.market_code"
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def latest_prices(conn: sqlite3.Connection, d: str | None = None) -> list[sqlite3.Row]:
    """各市场各品种最新一天的价格（横向对比表）。"""
    if d is None:
        d = conn.execute("SELECT MAX(quote_date) AS d FROM quotes").fetchone()["d"]
    if not d:
        return []
    return conn.execute(
        "SELECT v.name AS variety_name, v.category, q.market_code, m.name AS market_name, "
        "q.price_per_kg, q.quote_date FROM quotes q "
        "JOIN varieties v ON v.code=q.variety_code "
        "JOIN markets m ON m.code=q.market_code "
        "WHERE q.quote_date=? ORDER BY v.category, v.name, q.market_code",
        (d,),
    ).fetchall()


def market_compare(conn: sqlite3.Connection, variety_code: str, start: str, end: str) -> list[dict]:
    """某品种区间内各市场均价对比。"""
    rows = conn.execute(
        "SELECT q.market_code, m.name AS market_name, "
        "ROUND(AVG(q.price_per_kg),2) AS avg_price, "
        "ROUND(MIN(q.price_per_kg),2) AS min_price, "
        "ROUND(MAX(q.price_per_kg),2) AS max_price, COUNT(*) AS n "
        "FROM quotes q JOIN markets m ON m.code=q.market_code "
        "WHERE q.variety_code=? AND q.quote_date BETWEEN ? AND ? "
        "GROUP BY q.market_code ORDER BY avg_price",
        (variety_code, start, end),
    ).fetchall()
    return [dict(r) for r in rows]
