import datetime
from ainews import db
from ainews.models import NewsItem


def _conn():
    c = db.get_conn(":memory:")
    db.init_db(c)
    return c


def test_upsert_dedup():
    c = _conn()
    item = NewsItem(source="xq", title="降准", external_id="1",
                    published_at=datetime.datetime(2026, 7, 23, 8, 0))
    assert db.upsert_news(c, item) is True
    assert db.upsert_news(c, item) is False  # 第二次去重
    rows = db.query_news(c)
    assert len(rows) == 1
    assert rows[0]["title"] == "降准"


def test_query_filters_by_source_and_category():
    c = _conn()
    db.upsert_news(c, NewsItem(source="xq", title="A", external_id="1", category="A股"))
    db.upsert_news(c, NewsItem(source="sina", title="B", external_id="2", category="外汇期货"))
    assert len(db.query_news(c, source="xq")) == 1
    assert len(db.query_news(c, category="外汇期货")) == 1
    assert db.query_news(c, category="外汇期货")[0]["source"] == "sina"


def test_record_fetch_run():
    c = _conn()
    now = datetime.datetime(2026, 7, 23, 8, 0)
    db.record_fetch_run(c, "xq", now, now, fetched_count=10, new_count=3, status="ok")
    cur = c.execute("SELECT source, new_count, status FROM fetch_runs")
    row = cur.fetchone()
    assert row[0] == "xq" and row[1] == 3 and row[2] == "ok"
