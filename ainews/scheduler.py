"""后台调度：按每源 poll_interval 周期性抓取。"""
import logging
import time

import schedule

from ainews import pipeline

logger = logging.getLogger(__name__)


def start_scheduler(conn_factory, sources: list[dict], stop_event=None) -> None:
    for s in sources:
        interval = int(s.get("poll_interval", 300))
        schedule.every(interval).seconds.do(
            lambda cfg=s: pipeline.run_source(conn_factory(), cfg))
    # 启动即先跑一轮
    pipeline.run_all(conn_factory(), sources)
    logger.info("调度器启动，%d 个源", len(sources))
    while stop_event is None or not stop_event.is_set():
        schedule.run_pending()
        time.sleep(1)
