"""CLI 入口冒烟：子进程真实执行 init/collect/backfill，防止入口参数回归。"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_cli_init_collect_backfill(tmp_path, mock_servers):
    env = dict(os.environ)
    env["AGRI_DB"] = str(tmp_path / "cli_test.db")
    env["AGRI_TODAY"] = "2026-11-13"
    # 子进程 cwd 在临时目录，需要把项目根加进模块搜索路径
    env["PYTHONPATH"] = str(PROJECT_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    for code, port in mock_servers.items():
        env[f"AGRI_MARKET_{code}_URL"] = f"http://127.0.0.1:{port}"

    def run(*args):
        return subprocess.run(
            [sys.executable, "-m", "agri.cli", *args],
            capture_output=True, text=True, env=env, cwd=tmp_path,
        )

    r1 = run("init")
    assert r1.returncode == 0, r1.stderr
    assert "初始化完成" in r1.stdout

    # 重复 init 应跳过，不复活运营数据
    r1b = run("init")
    assert r1b.returncode == 0
    assert "跳过" in r1b.stdout

    r2 = run("collect", "--market", "A", "--date", "2026-11-11")
    assert r2.returncode == 0, r2.stderr
    assert "success" in r2.stdout

    r3 = run("backfill", "--days", "5")
    assert r3.returncode == 0, r3.stderr

    # 休市日命令行也能正常返回 closed
    r4 = run("collect", "--market", "A", "--date", "2026-10-01")
    assert r4.returncode == 0
    assert "closed" in r4.stdout
