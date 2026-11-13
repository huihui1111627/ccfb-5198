"""品种映射服务：原始品名 -> 标准品种，含未识别品名登记。"""
from __future__ import annotations

import sqlite3


def resolve_variety(conn: sqlite3.Connection, market_code: str, raw_name: str) -> str | None:
    row = conn.execute(
        "SELECT variety_code FROM variety_aliases WHERE market_code=? AND raw_name=?",
        (market_code, raw_name.strip()),
    ).fetchone()
    return row["variety_code"] if row else None


def register_unmapped(conn: sqlite3.Connection, market_code: str, raw_name: str, raw_unit: str = "") -> None:
    conn.execute(
        "INSERT INTO unmapped_quotes(market_code,raw_name,raw_unit,hit_count) VALUES(?,?,?,1) "
        "ON CONFLICT(market_code,raw_name) DO UPDATE SET "
        "hit_count=hit_count+1, last_seen=datetime('now','localtime'), raw_unit=excluded.raw_unit",
        (market_code, raw_name.strip(), raw_unit),
    )


def add_alias(conn: sqlite3.Connection, market_code: str, raw_name: str, variety_code: str) -> None:
    conn.execute(
        "INSERT INTO variety_aliases(market_code,raw_name,variety_code) VALUES(?,?,?) "
        "ON CONFLICT(market_code,raw_name) DO UPDATE SET variety_code=excluded.variety_code",
        (market_code, raw_name.strip(), variety_code),
    )
    # 映射补齐后从待处理清单移除
    conn.execute(
        "DELETE FROM unmapped_quotes WHERE market_code=? AND raw_name=?",
        (market_code, raw_name.strip()),
    )


def delete_alias(conn: sqlite3.Connection, alias_id: int) -> None:
    conn.execute("DELETE FROM variety_aliases WHERE id=?", (alias_id,))


def list_aliases(conn: sqlite3.Connection, market_code: str | None = None) -> list[sqlite3.Row]:
    sql = (
        "SELECT a.id, a.market_code, m.name AS market_name, a.raw_name, a.variety_code, v.name AS variety_name "
        "FROM variety_aliases a JOIN markets m ON m.code=a.market_code "
        "JOIN varieties v ON v.code=a.variety_code"
    )
    params: tuple = ()
    if market_code:
        sql += " WHERE a.market_code=?"
        params = (market_code,)
    sql += " ORDER BY a.market_code, a.variety_code"
    return conn.execute(sql, params).fetchall()


def list_unmapped(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT u.*, m.name AS market_name FROM unmapped_quotes u "
        "JOIN markets m ON m.code=u.market_code ORDER BY u.hit_count DESC"
    ).fetchall()
