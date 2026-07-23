"""抓取编排：单源抓取→入库→记录运行；失败隔离。"""
import datetime
import logging

from ainews import db, fetcher

logger = logging.getLogger(__name__)


def run_source(conn, source_cfg: dict, fetch=fetcher.fetch_source) -> dict:
    started = datetime.datetime.now()
    source_id = source_cfg.get("id", "?")
    try:
        items = fetch(source_cfg)
        new = sum(1 for it in items if db.upsert_news(conn, it))
        finished = datetime.datetime.now()
        db.record_fetch_run(conn, source_id, started, finished,
                            fetched_count=len(items), new_count=new, status="ok")
        logger.info("源 %s 抓取 %d 条，新增 %d 条", source_id, len(items), new)
        return {"fetched": len(items), "new": new, "status": "ok"}
    except Exception as e:  # 失败隔离：一个源挂掉不影响其他
        finished = datetime.datetime.now()
        db.record_fetch_run(conn, source_id, started, finished,
                            fetched_count=0, new_count=0, status="error", error=str(e))
        logger.warning("源 %s 抓取失败: %s", source_id, e)
        return {"fetched": 0, "new": 0, "status": "error"}


def run_all(conn, sources: list[dict]) -> list[dict]:
    return [run_source(conn, s) for s in sources]
