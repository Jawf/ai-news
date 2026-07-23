"""配置驱动源适配器：按 source_cfg 抓取 + JSONPath 映射为 NewsItem。"""
import datetime

import httpx
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


def fetch_source(source_cfg: dict, client: httpx.Client | None = None) -> list[NewsItem]:
    owns = client is None
    client = client or httpx.Client(timeout=15)
    try:
        resp = client.request(
            source_cfg.get("method", "GET").upper(),
            source_cfg["endpoint"],
            params=source_cfg.get("params") or None,
            headers=source_cfg.get("headers") or None,
        )
        resp.raise_for_status()
        return normalize(resp.json(), source_cfg)
    finally:
        if owns:
            client.close()
