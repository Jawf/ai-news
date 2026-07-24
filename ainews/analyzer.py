"""Claude 批量分析：当日新闻 → Top20/利好利空/公司归类/Top5 洞察快照。"""
import datetime
import json
import logging
import re
import subprocess

from ainews import db

logger = logging.getLogger(__name__)

_CONTRACT = """{
  "top20": [{"title": "...", "source": "...", "importance": 0-100,
             "sentiment": "利好|利空|中性", "sectors": ["..."],
             "stocks": [{"name": "...", "code": "..."}], "reason": "一句影响判断"}],
  "bullish": {"directions": ["..."], "sectors": ["..."], "stocks": [{"name": "...", "code": "..."}]},
  "bearish": {"directions": ["..."], "sectors": ["..."], "stocks": [{"name": "...", "code": "..."}]},
  "company_sina": [{"company": "...", "sentiment": "利好|利空", "summary": "..."}],
  "top5_bullish": [{"title": "...", "reason": "..."}]
}"""


def build_analysis_prompt(items: list[dict], date_cn: str) -> str:
    news_json = json.dumps(
        [{"source": it.get("source", ""), "title": it.get("title", ""),
          "content": (it.get("content") or "")[:200]} for it in items],
        ensure_ascii=False)
    return (
        f"今天是{date_cn}。以下是今日抓取的财经新闻(JSON 数组)：\n{news_json}\n\n"
        "请完成：\n"
        "1. 综合影响力/重要性选出 top20（每条给 importance 0-100、sentiment、涉及板块 sectors、"
        "涉及个股 stocks(名称+代码)、一句 reason）；\n"
        "2. 归纳整体利好 bullish 与利空 bearish 的方向 directions、板块 sectors、个股 stocks；\n"
        "3. 对 source 为 sina 的公司类资讯，按公司归类利好/利空，写入 company_sina；\n"
        "4. 从利好中精选 top5_bullish 并给理由。\n\n"
        f"只输出一个 JSON 对象（不要任何其他文字），结构如下：\n{_CONTRACT}"
    )


def parse_analysis_output(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise ValueError("输出中未找到 JSON 对象")
    return json.loads(m.group(0))


def _default_runner(prompt: str, config: dict) -> str:
    # prompt 走 stdin 而非 argv：Windows 命令行长度上限 32767 字符，
    # 真实一天的 prompt（约 1000 条新闻，约 150KB）会超限导致进程无法启动；
    # `claude --print` 不带位置参数时会从 stdin（管道输入）读取 prompt。
    cmd = [config.get("claude_command", "claude"), "--print",
           "--output-format", "text", "--dangerously-skip-permissions"]
    result = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8",
                            timeout=config.get("timeout_seconds", 600))
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip()[:500] or "claude CLI 非零退出")
    return result.stdout


def run_analysis(config: dict, conn, runner=None) -> bool:
    runner = runner or _default_runner
    started = datetime.datetime.now()
    date_str = datetime.date.today().strftime("%Y-%m-%d")
    date_cn = datetime.date.today().strftime("%Y年%m月%d日")
    items = db.query_news(conn, date=date_str, limit=500)
    if not items:  # 当天无数据退回最近 200 条
        items = db.query_news(conn, limit=200)
    if not items:
        db.save_analysis_run(conn, started, "error", error="无新闻可分析")
        return False
    try:
        raw = runner(build_analysis_prompt(items, date_cn), config)
        payload = parse_analysis_output(raw)
        db.save_analysis_run(conn, started, "ok", payload=payload)
        logger.info("分析完成：top20=%d 条", len(payload.get("top20", [])))
        return True
    except Exception as e:
        db.save_analysis_run(conn, started, "error", error=str(e)[:1000])
        logger.warning("分析失败: %s", e)
        return False
