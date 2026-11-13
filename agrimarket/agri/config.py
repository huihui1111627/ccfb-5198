"""全局配置：路径、端口、日期窗口。所有取值都允许用环境变量覆盖，方便测试。"""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("AGRI_DATA_DIR", BASE_DIR / "data"))
DEFAULT_DB_PATH = DATA_DIR / "agri.db"

# 三个 mock 市场的默认端口
MARKET_PORTS = {"A": 8601, "B": 8602, "C": 8603}

# mock 数据窗口起点（造数据用）
WINDOW_START = date(2026, 9, 1)

WEB_HOST = os.environ.get("AGRI_WEB_HOST", "127.0.0.1")
WEB_PORT = int(os.environ.get("AGRI_WEB_PORT", "8610"))


def get_db_path() -> Path:
    return Path(os.environ.get("AGRI_DB", DEFAULT_DB_PATH))


def market_url(market_code: str) -> str:
    """市场地址，优先读 AGRI_MARKET_X_URL 环境变量。"""
    env = os.environ.get(f"AGRI_MARKET_{market_code}_URL")
    if env:
        return env.rstrip("/")
    return f"http://127.0.0.1:{MARKET_PORTS[market_code]}"


def today() -> date:
    """当天日期，AGRI_TODAY 可覆盖（演示/测试用）。"""
    override = os.environ.get("AGRI_TODAY")
    if override:
        return date.fromisoformat(override)
    return date.today()
