import httpx
import respx
from ainews import fetcher


SOURCE = {
    "id": "xq", "name": "雪球",
    "endpoint": "https://example.com/news",
    "method": "GET", "params": {}, "headers": {},
    "mapping": {
        "list_path": "$.data.items",
        "external_id": "$.id",
        "time": "$.created_at",
        "title": "$.title",
        "content": "$.text",
        "url": "$.target",
    },
}

SAMPLE = {"data": {"items": [
    {"id": "1", "created_at": "2026-07-23T08:00:00", "title": "央行降准",
     "text": "释放流动性", "target": "https://x.com/1"},
    {"id": "2", "created_at": "2026-07-23T08:05:00", "title": "无关公告",
     "text": "普通内容", "target": "https://x.com/2"},
]}}


def test_normalize_maps_fields_and_classifies():
    items = fetcher.normalize(SAMPLE, SOURCE)
    assert len(items) == 2
    assert items[0].source == "xq"
    assert items[0].title == "央行降准"
    assert items[0].external_id == "1"
    assert items[0].url == "https://x.com/1"
    assert items[0].category == "宏观政策"


@respx.mock
def test_fetch_source_http():
    respx.get("https://example.com/news").mock(
        return_value=httpx.Response(200, json=SAMPLE))
    items = fetcher.fetch_source(SOURCE)
    assert len(items) == 2
    assert items[1].title == "无关公告"
