"""组装应用：DB + 缓存 + 后台调度线程 + FastAPI。"""
import os
import threading

from ainews import analyzer
from ainews import config as cfg_mod
from ainews import db, scheduler, trader, web
from ainews.cache import QueryCache

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(_BASE, "news.db")


def build_app(config: dict, sources: list[dict]):
    db.init_db(db.get_conn(DB_PATH))  # 确保表存在

    def conn_factory():
        return db.get_conn(DB_PATH)

    cache = QueryCache(ttl=float(config.get("cache_ttl", 45)))
    app = web.create_app(conn_factory, cache, config=config)

    if config.get("scheduler_enabled", True) and sources:
        analysis_times = config.get("analysis_times", ["08:00", "12:00"])

        def _analysis_and_trade():
            analyzer.run_analysis(config, conn_factory())
            trader.run_trading(config, conn_factory())

        t = threading.Thread(
            target=scheduler.start_scheduler,
            args=(conn_factory, sources),
            kwargs={"analysis_job": _analysis_and_trade,
                    "analysis_times": analysis_times,
                    "cleanup_job": lambda: db.purge_old_news(
                        conn_factory(), days=int(config.get("retention_days", 30))),
                    "cleanup_time": config.get("cleanup_time", "03:30"),
                    "stops_job": lambda: trader.run_patrol(config, conn_factory())},
            daemon=True)
        t.start()
    return app, conn_factory
