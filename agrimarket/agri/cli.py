"""命令行入口：python -m agri.cli <command>

init       初始化数据库与基础数据
mocks      启动三个 mock 市场站
collect    立即采集（默认今天，可指定日期/市场）
backfill   补采漏失日期
web        启动网页控制台（含定时任务）
scheduler  仅启动定时调度进程
"""
from __future__ import annotations

import argparse
import logging
from datetime import date

from .config import WEB_HOST, WEB_PORT
from .mocks.serve import serve_all
from .seed import seed
from .services.runner import backfill, collect_all, run_market_day
from .services.scheduler import shutdown_scheduler, start_scheduler


def _print_results(results) -> None:
    for r in results:
        print(f"{r.market_code}  {r.quote_date}  {r.status:<8}  {r.message}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="agri", description="农批行情采集系统")
    sub = parser.add_subparsers(dest="cmd", required=True)

    init_p = sub.add_parser("init", help="初始化数据库与基础数据（已初始化则跳过）")
    init_p.add_argument("--force", action="store_true", help="强制重建基础数据")

    mocks = sub.add_parser("mocks", help="启动三个 mock 市场站")
    mocks.add_argument("--host", default="127.0.0.1")

    col = sub.add_parser("collect", help="立即采集一次")
    col.add_argument("--market", choices=["A", "B", "C"], help="只采某个市场")
    col.add_argument("--date", help="指定日期 YYYY-MM-DD，默认今天")

    bf = sub.add_parser("backfill", help="补采过去 N 天")
    bf.add_argument("--market", choices=["A", "B", "C"])
    bf.add_argument("--days", type=int, default=15)
    bf.add_argument("--force", action="store_true", help="已成功的日期也重采")

    web = sub.add_parser("web", help="启动网页控制台")
    web.add_argument("--host", default=WEB_HOST)
    web.add_argument("--port", type=int, default=WEB_PORT)
    web.add_argument("--no-scheduler", action="store_true")

    sub.add_parser("scheduler", help="只跑定时调度进程")

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.cmd == "init":
        did = seed(force=getattr(args, "force", False))
        print("数据库初始化完成" if did else "数据库已存在，跳过初始化（--force 可重建基础数据）")

    elif args.cmd == "mocks":
        serve_all(args.host)
        try:
            import threading
            threading.Event().wait()
        except KeyboardInterrupt:
            pass

    elif args.cmd == "collect":
        seed()
        target = date.fromisoformat(args.date) if args.date else None
        if args.market:
            if target is None:
                from .config import today
                target = today()
            _print_results([run_market_day(args.market, target)])
        else:
            _print_results(collect_all(target))

    elif args.cmd == "backfill":
        seed()
        _print_results(backfill(args.market, args.days, force=args.force))

    elif args.cmd == "web":
        from .web.app import create_app
        seed()
        app = create_app()
        if not args.no_scheduler:
            start_scheduler()
        print(f"控制台: http://{args.host}:{args.port}")
        try:
            app.run(host=args.host, port=args.port, use_reloader=False)
        finally:
            shutdown_scheduler()

    elif args.cmd == "scheduler":
        seed()
        start_scheduler()
        print("定时调度进程已启动，Ctrl+C 退出")
        try:
            import threading
            threading.Event().wait()
        except KeyboardInterrupt:
            shutdown_scheduler()


if __name__ == "__main__":
    main()
