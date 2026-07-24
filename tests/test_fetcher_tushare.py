import datetime
import os

import httpx
import pytest
import respx

from ainews import fetcher

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "tushare_xq_sample.html")

XQ_SOURCE = {
    "id": "xq", "name": "雪球", "type": "html",
    "mapping": {
        "item_selector": ".news_item",
        "time_selector": ".news_datetime",
        "content_selector": ".news_content",
    },
}

XQ_SOURCE_HTTP = {
    **XQ_SOURCE,
    "endpoint": "https://example.com/tushare",
    "method": "GET", "params": {}, "headers": {},
}


def test_normalize_html_maps_and_classifies():
    with open(FIX, encoding="utf-8") as f:
        html = f.read()
    items = fetcher.normalize_html(html, XQ_SOURCE)
    assert len(items) == 6
    assert all(it.title for it in items)          # title = 正文全文
    assert items[0].source == "xq"
    # 第 4 条(人民币兑美元中间价)应归外汇期货
    forex = [it for it in items if "人民币兑美元" in it.title]
    assert forex and forex[0].category == "外汇期货"


def test_normalize_html_published_today_with_hhmm():
    with open(FIX, encoding="utf-8") as f:
        html = f.read()
    items = fetcher.normalize_html(html, XQ_SOURCE)
    today = datetime.date.today()
    assert items[0].published_at.date() == today
    assert items[0].published_at.hour == 9 and items[0].published_at.minute == 21


def test_dedup_hash_stable_without_external_id():
    with open(FIX, encoding="utf-8") as f:
        html = f.read()
    a = fetcher.normalize_html(html, XQ_SOURCE)
    b = fetcher.normalize_html(html, XQ_SOURCE)
    assert a[0].content_hash == b[0].content_hash   # 同源同正文同时间 → 稳定去重键


@respx.mock
def test_fetch_source_html_raises_on_gate_skeleton_page():
    respx.get("https://example.com/tushare").mock(
        return_value=httpx.Response(200, text='<div id="app"></div>'))
    with pytest.raises(RuntimeError, match="未登录或 cookie 失效"):
        fetcher.fetch_source(XQ_SOURCE_HTTP)


def _build_html(times: list[str]) -> str:
    items_html = "".join(
        f'<div class="news_item"><div class="news_datetime">{t}</div>'
        f'<div class="news_content">内容{i}</div></div>'
        for i, t in enumerate(times)
    )
    return f'<div class="news_data cur">{items_html}</div>'


def test_normalize_html_infers_previous_day_when_time_rewinds_upward():
    # 倒序(新→旧)列表跨越午夜：10:00,09:00 属今天；23:30,22:00 时间回升 → 属昨天
    html = _build_html(["10:00", "09:00", "23:30", "22:00"])
    now = datetime.datetime(2026, 7, 24, 10, 30)
    items = fetcher.normalize_html(html, XQ_SOURCE, now=now)
    assert len(items) == 4
    assert items[0].published_at == datetime.datetime(2026, 7, 24, 10, 0)
    assert items[1].published_at == datetime.datetime(2026, 7, 24, 9, 0)
    assert items[2].published_at == datetime.datetime(2026, 7, 23, 23, 30)
    assert items[3].published_at == datetime.datetime(2026, 7, 23, 22, 0)


def test_normalize_html_first_item_future_time_is_yesterday():
    # 首条时间晚于 now(未来) → 首条其实是昨天 23:59 的旧闻，而非今天
    html = _build_html(["23:59", "23:00"])
    now = datetime.datetime(2026, 7, 24, 8, 0)
    items = fetcher.normalize_html(html, XQ_SOURCE, now=now)
    assert items[0].published_at == datetime.datetime(2026, 7, 23, 23, 59)
    assert items[1].published_at == datetime.datetime(2026, 7, 23, 23, 0)


@respx.mock
def test_fetch_source_html_returns_normally_with_news_data_container():
    with open(FIX, encoding="utf-8") as f:
        html = f.read()
    respx.get("https://example.com/tushare").mock(
        return_value=httpx.Response(200, text=html))
    items = fetcher.fetch_source(XQ_SOURCE_HTTP)
    assert len(items) == 6
