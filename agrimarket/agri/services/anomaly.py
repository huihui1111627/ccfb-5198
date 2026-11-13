"""异常价格检测：同市场同品种，相对上一个开市日报价的环比突变。"""
from __future__ import annotations

import sqlite3

from ..db import get_setting


def threshold_pct(conn: sqlite3.Connection) -> float:
    try:
        return float(get_setting(conn, "anomaly_pct", "30"))
    except (TypeError, ValueError):
        return 30.0


def previous_quote(conn: sqlite3.Connection, market_code: str, variety_code: str,
                   before_date: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM quotes WHERE market_code=? AND variety_code=? AND quote_date < ? "
        "ORDER BY quote_date DESC LIMIT 1",
        (market_code, variety_code, before_date),
    ).fetchone()


def evaluate_quote(conn: sqlite3.Connection, quote_row: sqlite3.Row) -> int | None:
    """对一条新/更新后的行情做异常判定，返回 anomaly id（无异常返回 None）。

    判定规则：与同市场同品种上一开市日相比，涨跌幅绝对值超过阈值即标异常。
    已经存在未处理异常的不重复登记；行情被重采覆盖后同步重算。
    """
    pct_limit = threshold_pct(conn)
    prev = previous_quote(conn, quote_row["market_code"], quote_row["variety_code"],
                          quote_row["quote_date"])
    change_pct = None
    if prev and prev["price_per_kg"] > 0:
        change_pct = round(
            (quote_row["price_per_kg"] - prev["price_per_kg"]) / prev["price_per_kg"] * 100, 2
        )

    # 该 quote 旧的异常记录先清掉 pending 状态的（重算场景）
    conn.execute(
        "DELETE FROM anomalies WHERE quote_id=? AND status='pending'",
        (quote_row["id"],),
    )

    if change_pct is not None and abs(change_pct) >= pct_limit:
        cur = conn.execute(
            "INSERT INTO anomalies(quote_id,market_code,quote_date,variety_code,"
            "price_per_kg,prev_price,change_pct,status) VALUES(?,?,?,?,?,?,?,'pending')",
            (
                quote_row["id"], quote_row["market_code"], quote_row["quote_date"],
                quote_row["variety_code"], quote_row["price_per_kg"],
                prev["price_per_kg"], change_pct,
            ),
        )
        return cur.lastrowid
    return None


def list_anomalies(conn: sqlite3.Connection, status: str | None = None) -> list[sqlite3.Row]:
    sql = (
        "SELECT an.*, v.name AS variety_name, m.name AS market_name, q.raw_name, q.raw_price, q.raw_unit "
        "FROM anomalies an JOIN varieties v ON v.code=an.variety_code "
        "JOIN markets m ON m.code=an.market_code "
        "JOIN quotes q ON q.id=an.quote_id"
    )
    if status:
        sql += " WHERE an.status=?"
        return conn.execute(sql + " ORDER BY an.quote_date DESC, an.id DESC", (status,)).fetchall()
    return conn.execute(sql + " ORDER BY an.status, an.quote_date DESC, an.id DESC").fetchall()


def handle(conn: sqlite3.Connection, anomaly_id: int, action: str, note: str = "") -> None:
    """人工确认 / 忽略。"""
    if action not in ("confirmed", "dismissed"):
        raise ValueError("action 只能是 confirmed 或 dismissed")
    conn.execute(
        "UPDATE anomalies SET status=?, note=?, handled_at=datetime('now','localtime') WHERE id=?",
        (action, note, anomaly_id),
    )
