import datetime
import os

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
