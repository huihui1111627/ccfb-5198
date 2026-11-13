"""pytest 公共夹具：隔离的临时数据库 + 三个 mock 站（测试端口）。"""
from __future__ import annotations

import os
import socket
from datetime import date, timedelta
from pathlib import Path

import pytest

from agri.db import init_db
from agri.mocks.app import APPS
from agri.seed import seed

TEST_PORTS = {"A": 8701, "B": 8702, "C": 8703}
TEST_TODAY = date(2026, 11, 13)


def _free(port: int) -> bool:
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


@pytest.fixture(scope="session")
def mock_servers():
    if not all(_free(p) for p in TEST_PORTS.values()):
        pytest.skip("测试端口 8701-8703 被占用")
    from werkzeug.serving import make_server
    import threading

    servers = []
    for code, factory in APPS.items():
        httpd = make_server("127.0.0.1", TEST_PORTS[code], factory(), threaded=True)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        servers.append(httpd)
    yield TEST_PORTS
    for s in servers:
        s.shutdown()


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "test_agri.db"
    # 让 market_url 走测试端口
    for code, port in TEST_PORTS.items():
        os.environ[f"AGRI_MARKET_{code}_URL"] = f"http://127.0.0.1:{port}"
    seed(path)
    init_db(path)
    return path


@pytest.fixture
def market_urls():
    return {code: f"http://127.0.0.1:{port}" for code, port in TEST_PORTS.items()}


@pytest.fixture
def an_open_day() -> date:
    """窗口内一个确定的开市日（周三）。"""
    return date(2026, 11, 11)


@pytest.fixture
def holiday_day() -> date:
    return date(2026, 10, 1)  # 国庆


def pytest_addoption(parser):
    parser.addoption("--with-browser", action="store_true",
                     help="运行依赖 Playwright 浏览器的用例（默认也跑，除非浏览器缺失）")


@pytest.fixture
def browser_available():
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            browser.close()
        return True
    except Exception:
        return False
