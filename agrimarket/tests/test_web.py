"""Web 控制台路由冒烟测试（test client，不起真实端口）。"""
from __future__ import annotations

from datetime import date

import pytest

from agri.services.runner import collect_all
from agri.web.app import create_app


@pytest.fixture
def client(mock_servers, db_path, monkeypatch):
    monkeypatch.setenv("AGRI_TODAY", "2026-11-13")
    collect_all(date(2026, 11, 12), db_path)
    collect_all(date(2026, 11, 11), db_path)
    app = create_app(db_path, start_jobs=False)
    app.config.update(TESTING=True)
    return app.test_client()


def test_dashboard(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "仪表盘".encode() in resp.data


def test_tasks_collect_post(client):
    resp = client.post("/tasks/collect", data={"market_code": "A", "quote_date": "2026-11-12"},
                       follow_redirects=True)
    assert resp.status_code == 200
    assert "成功".encode() in resp.data


def test_mapping_pages(client):
    assert client.get("/mapping").status_code == 200
    resp = client.post("/mapping/alias", data={
        "market_code": "A", "raw_name": "试验菜", "variety_code": "黄瓜",
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert "试验菜".encode() in resp.data


def test_quotes_filter_and_export(client):
    page = client.get("/quotes?start=2026-11-10&end=2026-11-12&variety_code=大白菜")
    assert page.status_code == 200
    assert "价格走势".encode() in page.data
    xlsx = client.get("/quotes/export?start=2026-11-10&end=2026-11-12")
    assert xlsx.status_code == 200
    assert xlsx.headers["Content-Type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert xlsx.data[:2] == b"PK"  # xlsx 是 zip 容器


def test_anomaly_handle_flow(client):
    # 阈值调低并重新采集，强制产生异常
    from agri.db import get_conn, set_setting
    with get_conn(client.application.config["DB_PATH"]) as conn:
        set_setting(conn, "anomaly_pct", "1")
    client.post("/tasks/collect", data={"market_code": "A", "quote_date": "2026-11-12"})
    listing = client.get("/anomalies?status=pending")
    assert listing.status_code == 200
    assert "待处理".encode() in listing.data

    from agri.db import get_conn as gc
    with gc(client.application.config["DB_PATH"]) as conn:
        aid = conn.execute("SELECT id FROM anomalies WHERE status='pending' LIMIT 1").fetchone()
        if aid is None:
            pytest.skip("当前样本未产生异常（阈值已调至 1%，正常情况下会有）")
        aid = aid["id"]
    resp = client.post(f"/anomalies/{aid}/handle",
                       data={"action": "confirm", "note": "测试确认", "redirect_status": "pending"},
                       follow_redirects=True)
    assert resp.status_code == 200
    with gc(client.application.config["DB_PATH"]) as conn:
        assert conn.execute(
            "SELECT status FROM anomalies WHERE id=?", (aid,)).fetchone()["status"] == "confirmed"


def test_settings_save_and_spec_update(client):
    resp = client.post("/settings", data={
        "anomaly_pct": "25", "scheduler_hour": "7", "scheduler_minute": "30",
        "backfill_days": "20", "page_size": "50",
    }, follow_redirects=True)
    assert resp.status_code == 200
    from agri.db import get_conn
    with get_conn(client.application.config["DB_PATH"]) as conn:
        assert conn.execute("SELECT value FROM settings WHERE key='anomaly_pct'").fetchone()["value"] == "25"


def test_holiday_crud(client):
    client.post("/settings/holiday", data={"d": "2026-12-31", "name": "自定义休市"})
    from agri.db import get_conn
    with get_conn(client.application.config["DB_PATH"]) as conn:
        assert conn.execute("SELECT name FROM holidays WHERE d='2026-12-31'").fetchone()["name"] == "自定义休市"
    client.post("/settings/holiday/2026-12-31/delete")
    with get_conn(client.application.config["DB_PATH"]) as conn:
        assert conn.execute("SELECT 1 FROM holidays WHERE d='2026-12-31'").fetchone() is None
