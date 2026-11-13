"""异常检测：环比突变阈值、人工确认/忽略、重采重算。"""
from __future__ import annotations

from agri.db import get_conn, set_setting
from agri.services.anomaly import evaluate_quote, handle, list_anomalies


def _insert_quote(conn, market, d, variety, price):
    conn.execute(
        "INSERT INTO quotes(market_code,quote_date,variety_code,raw_name,raw_price,"
        "raw_unit,price_per_kg) VALUES(?,?,?,?,?,?,?)",
        (market, d, variety, variety, price, "元/公斤", price),
    )
    return conn.execute(
        "SELECT * FROM quotes WHERE market_code=? AND quote_date=? AND variety_code=?",
        (market, d, variety),
    ).fetchone()


def test_spike_flagged_and_normal_not(db_path):
    with get_conn(db_path) as conn:
        set_setting(conn, "anomaly_pct", "30")
        _insert_quote(conn, "A", "2026-11-10", "黄瓜", 4.0)
        normal = _insert_quote(conn, "A", "2026-11-11", "黄瓜", 4.2)   # +5%
        spike = _insert_quote(conn, "A", "2026-11-12", "黄瓜", 6.0)    # +42.9%

        assert evaluate_quote(conn, normal) is None
        anomaly_id = evaluate_quote(conn, spike)
        assert anomaly_id is not None
        rows = list_anomalies(conn, "pending")
        one = [r for r in rows if r["id"] == anomaly_id][0]
        assert one["change_pct"] > 30
        assert one["prev_price"] == 4.2


def test_plunge_also_flagged(db_path):
    with get_conn(db_path) as conn:
        _insert_quote(conn, "A", "2026-11-10", "土豆", 2.0)
        plunge = _insert_quote(conn, "A", "2026-11-11", "土豆", 1.2)  # -40%
        assert evaluate_quote(conn, plunge) is not None


def test_manual_confirm_and_dismiss(db_path):
    with get_conn(db_path) as conn:
        _insert_quote(conn, "A", "2026-11-10", "茄子", 4.0)
        q = _insert_quote(conn, "A", "2026-11-11", "茄子", 6.5)
        aid = evaluate_quote(conn, q)
        handle(conn, aid, "confirmed", "产地减产属实")
        rows = list_anomalies(conn, "confirmed")
        assert rows[0]["status"] == "confirmed"
        assert rows[0]["note"] == "产地减产属实"
        assert not list_anomalies(conn, "pending")


def test_recollect_recomputes_anomaly(db_path):
    """重采覆盖行情后，旧 pending 异常清除并按新价重算。"""
    with get_conn(db_path) as conn:
        _insert_quote(conn, "A", "2026-11-10", "辣椒", 7.0)
        q1 = _insert_quote(conn, "A", "2026-11-11", "辣椒", 11.0)  # +57% 异常
        assert evaluate_quote(conn, q1) is not None
        # 重采后价格回归正常
        conn.execute("UPDATE quotes SET price_per_kg=7.1 WHERE id=?", (q1["id"],))
        q2 = conn.execute("SELECT * FROM quotes WHERE id=?", (q1["id"],)).fetchone()
        assert evaluate_quote(conn, q2) is None
        assert not list_anomalies(conn, "pending")
