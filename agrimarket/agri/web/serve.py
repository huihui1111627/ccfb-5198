"""控制台启动入口：python -m agri.web.serve"""
from __future__ import annotations

import argparse
import logging

from ..config import WEB_HOST, WEB_PORT
from ..seed import seed
from .app import create_app
from ..services.scheduler import start_scheduler


def main() -> None:
    parser = argparse.ArgumentParser(description="启动农批行情采集控制台")
    parser.add_argument("--host", default=WEB_HOST)
    parser.add_argument("--port", type=int, default=WEB_PORT)
    parser.add_argument("--no-scheduler", action="store_true", help="不启动定时采集")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    seed()
    app = create_app()
    if not args.no_scheduler:
        start_scheduler()
    print(f"控制台已启动: http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, use_reloader=False)


if __name__ == "__main__":
    main()
