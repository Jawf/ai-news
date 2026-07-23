from fastapi.testclient import TestClient
from ainews import db, web
from ainews.cache import QueryCache
from ainews.models import NewsItem


def _app():
    conn = db.get_conn(":memory:")
    db.init_db(conn)
    db.upsert_news(conn, NewsItem(source="xq", title="央行降准", external_id="1", category="宏观政策"))
    db.upsert_news(conn, NewsItem(source="sina", title="A股上涨", external_id="2", category="A股"))
    return web.create_app(lambda: conn, QueryCache(ttl=30))


def test_index_html_lists_news():
    client = TestClient(_app())
    r = client.get("/")
    assert r.status_code == 200
    assert "央行降准" in r.text
    assert "A股上涨" in r.text


def test_api_news_json_filter():
    client = TestClient(_app())
    r = client.get("/api/news", params={"source": "xq"})
    assert r.status_code == 200
    data = r.json()
    assert len(data["items"]) == 1
    assert data["items"][0]["title"] == "央行降准"
