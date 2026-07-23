import datetime
from ainews.models import NewsItem


def test_content_hash_uses_external_id_when_present():
    a = NewsItem(source="xq", title="A", external_id="123")
    b = NewsItem(source="xq", title="不同标题", external_id="123")
    assert a.content_hash == b.content_hash  # 同源同 external_id 视为同一条


def test_content_hash_differs_by_source():
    a = NewsItem(source="xq", title="A", external_id="123")
    b = NewsItem(source="sina", title="A", external_id="123")
    assert a.content_hash != b.content_hash


def test_content_hash_falls_back_to_title_time():
    t = datetime.datetime(2026, 7, 23, 8, 0, 0)
    a = NewsItem(source="xq", title="无 id 新闻", published_at=t)
    b = NewsItem(source="xq", title="无 id 新闻", published_at=t)
    assert a.content_hash == b.content_hash
