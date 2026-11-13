"""SQLite 连接、建表、通用查询。"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .config import get_db_path

SCHEMA = """
CREATE TABLE IF NOT EXISTS markets (
    code        TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    source_type TEXT NOT NULL,          -- table / jsvar / excel
    base_url    TEXT NOT NULL,
    enabled     INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS varieties (
    code       TEXT PRIMARY KEY,        -- 标准品种 code，等同标准品名
    name       TEXT NOT NULL,           -- 标准品名
    category   TEXT NOT NULL,
    base_price REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS variety_aliases (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    market_code  TEXT NOT NULL,
    raw_name     TEXT NOT NULL,         -- 市场原始品名
    variety_code TEXT NOT NULL,
    UNIQUE(market_code, raw_name),
    FOREIGN KEY(market_code) REFERENCES markets(code),
    FOREIGN KEY(variety_code) REFERENCES varieties(code)
);

-- 箱/件规格按 市场+品种 配置；per_piece_price=0 时从行情单价推断（箱价/件价）
CREATE TABLE IF NOT EXISTS package_specs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    market_code  TEXT NOT NULL,
    variety_code TEXT NOT NULL,
    pack_unit    TEXT NOT NULL,         -- 箱 / 件
    spec_kg      REAL NOT NULL,         -- 每包净重(公斤)
    per_piece_price REAL NOT NULL DEFAULT 0,
    UNIQUE(market_code, variety_code),
    FOREIGN KEY(market_code) REFERENCES markets(code),
    FOREIGN KEY(variety_code) REFERENCES varieties(code)
);

CREATE TABLE IF NOT EXISTS quotes (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    market_code  TEXT NOT NULL,
    quote_date   TEXT NOT NULL,         -- YYYY-MM-DD
    variety_code TEXT NOT NULL,
    raw_name     TEXT NOT NULL,
    raw_price    REAL NOT NULL,
    raw_unit     TEXT NOT NULL,
    price_per_kg REAL NOT NULL,         -- 归一后的 元/公斤
    origin       TEXT,
    grade        TEXT,
    collected_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE(market_code, quote_date, variety_code)
);
CREATE INDEX IF NOT EXISTS idx_quotes_date_variety ON quotes(quote_date, variety_code);
CREATE INDEX IF NOT EXISTS idx_quotes_market ON quotes(market_code, quote_date);

-- open / closed / failed / partial
CREATE TABLE IF NOT EXISTS collection_runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    market_code   TEXT NOT NULL,
    quote_date    TEXT NOT NULL,
    status        TEXT NOT NULL,
    fetched_count INTEGER NOT NULL DEFAULT 0,
    saved_count   INTEGER NOT NULL DEFAULT 0,
    closed_reason TEXT,
    message       TEXT,
    started_at    TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    finished_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_date ON collection_runs(quote_date);

-- pending / confirmed / dismissed
CREATE TABLE IF NOT EXISTS anomalies (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    quote_id        INTEGER NOT NULL,
    market_code     TEXT NOT NULL,
    quote_date      TEXT NOT NULL,
    variety_code    TEXT NOT NULL,
    price_per_kg    REAL NOT NULL,
    prev_price      REAL,
    change_pct      REAL,
    status          TEXT NOT NULL DEFAULT 'pending',
    note            TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    handled_at      TEXT,
    FOREIGN KEY(quote_id) REFERENCES quotes(id)
);
CREATE INDEX IF NOT EXISTS idx_anomalies_status ON anomalies(status);

-- 采到未识别品名时登记，等人工在品种映射页处理
CREATE TABLE IF NOT EXISTS unmapped_quotes (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    market_code  TEXT NOT NULL,
    raw_name     TEXT NOT NULL,
    raw_unit     TEXT,
    first_seen   TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    last_seen    TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    hit_count    INTEGER NOT NULL DEFAULT 1,
    UNIQUE(market_code, raw_name)
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS holidays (
    d    TEXT PRIMARY KEY,
    name TEXT NOT NULL
);
"""


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def get_conn(db_path: str | Path | None = None) -> Iterator[sqlite3.Connection]:
    conn = connect(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: str | Path | None = None) -> None:
    with get_conn(db_path) as conn:
        conn.executescript(SCHEMA)


def get_setting(conn: sqlite3.Connection, key: str, default: Any = None) -> Any:
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn: sqlite3.Connection, key: str, value: Any) -> None:
    conn.execute(
        "INSERT INTO settings(key, value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, str(value)),
    )
