"""启动三个 mock 市场站：python -m agri.mocks.serve"""
from __future__ import annotations

import argparse
import threading

from ..config import MARKET_PORTS
from .app import APPS


def serve_all(host: str = "127.0.0.1", ports: dict[str, int] | None = None) -> list:
    """同进程三个端口跑三个 mock 站（演示/测试用），返回 werkzeug server 列表。"""
    from werkzeug.serving import make_server

    ports = ports or MARKET_PORTS
    servers = []
    for code, factory in APPS.items():
        httpd = make_server(host, ports[code], factory(), threaded=True)
        t = threading.Thread(target=httpd.serve_forever, name=f"mock-{code}", daemon=True)
        t.start()
        servers.append(httpd)
        print(f"mock 市场 {code} 已启动: http://{host}:{ports[code]}")
    return servers


def main() -> None:
    parser = argparse.ArgumentParser(description="启动三个 mock 批发市场站点")
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    servers = serve_all(args.host)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        for s in servers:
            s.shutdown()


if __name__ == "__main__":
    main()
