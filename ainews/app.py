"""组装应用：DB + 缓存 + 后台调度线程 + FastAPI。"""
import os
import threading

from ainews import config as cfg_mod
from ainews import db, scheduler, web
from ainews.cache import QueryCache

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(_BASE, "news.db")


def build_app(config: dict, sources: list[dict]):
    db.init_db(db.get_conn(DB_PATH))  # 确保表存在

    def conn_factory():
        return db.get_conn(DB_PATH)

    cache = QueryCache(ttl=float(config.get("cache_ttl", 45)))
    app = web.create_app(conn_factory, cache)

    if config.get("scheduler_enabled", True) and sources:
        t = threading.Thread(
            target=scheduler.start_scheduler,
            args=(conn_factory, sources), daemon=True)
        t.start()
    return app, conn_factory
