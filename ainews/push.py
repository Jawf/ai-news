"""飞书推送（附加）：从库里选 Top-N，格式化后复用 job_runner 的发送逻辑。"""
import datetime
import logging

from ainews import db

logger = logging.getLogger(__name__)


def select_top_n(conn, n: int = 10, date: str | None = None) -> list[dict]:
    if date is None:
        date = datetime.date.today().strftime("%Y-%m-%d")
    rows = db.query_news(conn, date=date, limit=n, offset=0)
    if not rows:  # 当天无数据则退回最近 N 条
        rows = db.query_news(conn, limit=n, offset=0)
    return rows


def format_digest(items: list[dict], date: str) -> str:
    lines = [f"📰 {date} 财经TOP{len(items)}", ""]
    for i, it in enumerate(items, 1):
        lines.append(f"{i}. 【{it['source']}】{it['title']}")
        if it.get("content"):
            lines.append(f"   摘要：{it['content'][:50]}")
        lines.append("")
    return "\n".join(lines).strip()


def run_push(config: dict, conn, n: int = 10, sender=None) -> bool:
    if sender is None:
        from job_runner import send_news as sender  # 复用既有发送(nanobot + 飞书 API 兜底)
    date_cn = datetime.date.today().strftime("%Y年%m月%d日")
    items = select_top_n(conn, n=n)
    if not items:
        logger.warning("无新闻可推送")
        return False
    content = format_digest(items, date_cn)
    return sender(config, content, lambda m: logger.info(m))
