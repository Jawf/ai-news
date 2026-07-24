"""命令行入口：serve / fetch-once / push。"""
import argparse
import logging
import sys

import uvicorn

from ainews import app as app_mod
from ainews import config as cfg_mod
from ainews import db, pipeline, push

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")


def _load_config():
    return cfg_mod.load_config()


def _load_sources():
    return cfg_mod.load_sources()


def _open_conn():
    return db.get_conn(app_mod.DB_PATH)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ainews")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_serve = sub.add_parser("serve", help="启动 Web 服务 + 调度")
    p_serve.add_argument("--host", default="0.0.0.0")
    p_serve.add_argument("--port", type=int, default=8000)
    sub.add_parser("fetch-once", help="抓取一轮后退出")
    p_push = sub.add_parser("push", help="选 Top-N 推送飞书")
    p_push.add_argument("-n", type=int, default=10)
    sub.add_parser("analyze", help="立即跑一次 Claude 批量分析")
    sub.add_parser("purge", help="清理过期快讯（按 retention_days）")
    args = parser.parse_args(argv)

    if args.cmd == "serve":
        config, sources = _load_config(), _load_sources()
        application, _ = app_mod.build_app(config, sources)
        uvicorn.run(application, host=args.host, port=args.port)
        return 0

    if args.cmd == "fetch-once":
        conn = _open_conn()
        db.init_db(conn)
        results = pipeline.run_all(conn, _load_sources())
        print(f"抓取完成：{results}")
        return 0

    if args.cmd == "push":
        conn = _open_conn()
        db.init_db(conn)
        ok = push.run_push(_load_config(), conn, n=args.n)
        return 0 if ok else 1

    if args.cmd == "analyze":
        from ainews import analyzer
        conn = _open_conn()
        db.init_db(conn)
        ok = analyzer.run_analysis(_load_config(), conn)
        print("分析完成" if ok else "分析失败，详见 analysis_runs 表")
        return 0 if ok else 1

    if args.cmd == "purge":
        conn = _open_conn()
        db.init_db(conn)
        n = db.purge_old_news(conn, days=int(_load_config().get("retention_days", 30)))
        print(f"已清理 {n} 条过期快讯")
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
