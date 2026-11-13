#!/usr/bin/env bash
# 一键启动：三个 mock 市场站 + 网页控制台（含每日定时采集）
set -euo pipefail
cd "$(dirname "$0")"

export AGRI_TODAY="${AGRI_TODAY:-2026-11-13}"   # mock 数据窗口的“今天”，可按需改真实日期

echo "==> 初始化数据库"
python3 -m agri.cli init

echo "==> 启动三个 mock 市场站 (8601/8602/8603)"
python3 -m agri.cli mocks &
MOCK_PID=$!

cleanup() {
  echo ""
  echo "==> 正在退出..."
  kill "$MOCK_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

sleep 2
echo "==> 启动网页控制台 (8610)"
python3 -m agri.cli web
