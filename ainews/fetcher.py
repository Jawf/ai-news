"""配置驱动源适配器：按 source_cfg 抓取 + JSONPath/HTML 映射为 NewsItem。"""
import datetime
import os

import httpx
from bs4 import BeautifulSoup
from jsonpath_ng import parse as jp_parse

from ainews.classifier import classify
from ainews.models import NewsItem

_cache: dict[str, object] = {}


def _compile(path: str):
    if path not in _cache:
        _cache[path] = jp_parse(path)
    return _cache[path]


def _first(obj, path: str, default=""):
    if not path:
        return default
    matches = _compile(path).find(obj)
    return matches[0].value if matches else default


def _parse_time(raw) -> datetime.datetime | None:
    if not raw:
        return None
    if isinstance(raw, (int, float)):  # 毫秒/秒级时间戳
        ts = raw / 1000 if raw > 1e12 else raw
        return datetime.datetime.fromtimestamp(ts)
    try:
        return datetime.datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None


def normalize(raw: dict, source_cfg: dict) -> list[NewsItem]:
    mapping = source_cfg["mapping"]
    rows = _first(raw, mapping.get("list_path", "$"), default=[])
    if not isinstance(rows, list):
        rows = [rows]
    items: list[NewsItem] = []
    now = datetime.datetime.now()
    for row in rows:
        title = str(_first(row, mapping.get("title", ""))).strip()
        if not title:
            continue
        content = str(_first(row, mapping.get("content", "")))
        item = NewsItem(
            source=source_cfg["id"],
            title=title,
            content=content,
            url=str(_first(row, mapping.get("url", ""))),
            external_id=str(_first(row, mapping.get("external_id", ""))),
            published_at=_parse_time(_first(row, mapping.get("time", ""), default=None)),
            fetched_at=now,
        )
        item.category = classify(item.title, item.content)
        items.append(item)
    return items


def _resolve_headers(headers: dict | None) -> dict:
    """把 headers 值里的 ${ENV_VAR} 占位替换为环境变量。"""
    out = {}
    for k, v in (headers or {}).items():
        if isinstance(v, str) and v.startswith("${") and v.endswith("}"):
            out[k] = os.environ.get(v[2:-1], "")
        else:
            out[k] = v
    return out


def _today_at(hhmm: str) -> datetime.datetime | None:
    try:
        h, m = hhmm.strip().split(":")
        return datetime.datetime.combine(datetime.date.today(),
                                         datetime.time(int(h), int(m)))
    except (ValueError, AttributeError):
        return None


def normalize_html(html: str, source_cfg: dict) -> list[NewsItem]:
    m = source_cfg["mapping"]
    soup = BeautifulSoup(html, "html.parser")
    items = []
    now = datetime.datetime.now()
    for node in soup.select(m["item_selector"]):
        time_el = node.select_one(m["time_selector"])
        content_el = node.select_one(m["content_selector"])
        if not content_el:
            continue
        text = content_el.get_text(strip=True)
        if not text:
            continue
        item = NewsItem(
            source=source_cfg["id"],
            title=text,                 # 快讯即一句话，正文全文作标题
            content="",
            url="",
            external_id="",
            published_at=_today_at(time_el.get_text(strip=True)) if time_el else None,
            fetched_at=now,
        )
        item.category = classify(item.title, item.content)
        items.append(item)
    return items


def fetch_source(source_cfg: dict, client: httpx.Client | None = None) -> list[NewsItem]:
    owns = client is None
    client = client or httpx.Client(timeout=15)
    try:
        resp = client.request(
            source_cfg.get("method", "GET").upper(),
            source_cfg["endpoint"],
            params=source_cfg.get("params") or None,
            headers=_resolve_headers(source_cfg.get("headers")) or None,
        )
        resp.raise_for_status()
        if source_cfg.get("type") == "html":
            return normalize_html(resp.text, source_cfg)
        return normalize(resp.json(), source_cfg)
    finally:
        if owns:
            client.close()
