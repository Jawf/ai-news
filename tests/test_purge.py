import datetime
from ainews import db
from ainews.models import NewsItem


def _conn():
    c = db.get_conn(":memory:")
    db.init_db(c)
    return c


def test_purge_deletes_old_keeps_recent():
    c = _conn()
    now = datetime.datetime.now()
    old = NewsItem(source="xq", title="旧闻", external_id="1",
                   published_at=now - datetime.timedelta(days=40))
    recent = NewsItem(source="xq", title="新闻", external_id="2",
                       published_at=now - datetime.timedelta(days=1))
    db.upsert_news(c, old)
    db.upsert_news(c, recent)
    deleted = db.purge_old_news(c, days=30)
    assert deleted == 1
    rows = db.query_news(c)
    assert len(rows) == 1
    assert rows[0]["title"] == "新闻"


def test_purge_null_published_uses_fetched_at():
    c = _conn()
    now = datetime.datetime.now()
    item = NewsItem(source="xq", title="无发布时间", external_id="3",
                     published_at=None, fetched_at=now - datetime.timedelta(days=40))
    db.upsert_news(c, item)
    deleted = db.purge_old_news(c, days=30)
    assert deleted == 1
    assert db.query_news(c) == []


def test_purge_does_not_touch_analysis_runs():
    c = _conn()
    t = datetime.datetime.now() - datetime.timedelta(days=40)
    db.save_analysis_run(c, t, "ok", payload={"top20": [{"title": "降准"}]})
    db.purge_old_news(c, days=30)
    latest = db.latest_analysis(c)
    assert latest["top20"][0]["title"] == "降准"
