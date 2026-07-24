"""后台调度：按每源 poll_interval 周期性抓取。"""
import logging
import time

import schedule

from ainews import pipeline

logger = logging.getLogger(__name__)


def start_scheduler(conn_factory, sources: list[dict], stop_event=None,
                    analysis_job=None, analysis_times=None) -> None:
    for s in sources:
        interval = int(s.get("poll_interval", 300))
        schedule.every(interval).seconds.do(
            lambda cfg=s: pipeline.run_source(conn_factory(), cfg))
    if analysis_job and analysis_times:
        for t in analysis_times:
            schedule.every().day.at(t).do(analysis_job)
    # 启动即先跑一轮抓取
    pipeline.run_all(conn_factory(), sources)
    logger.info("调度器启动，%d 个源，%d 个分析定时点",
                len(sources), len(analysis_times or []) if analysis_job else 0)
    while stop_event is None or not stop_event.is_set():
        schedule.run_pending()
        time.sleep(1)
