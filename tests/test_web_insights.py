from fastapi.testclient import TestClient
from ainews import db, web
from ainews.cache import QueryCache


def _setup():
    conn = db.get_conn(":memory:")
    db.init_db(conn)
    db.save_analysis_run(conn, __import__("datetime").datetime.now(), "ok", payload={
        "top20": [{"title": "招商银行业绩超预期", "source": "xq", "importance": 90,
                   "sentiment": "利好", "sectors": ["银行"],
                   "stocks": [{"name": "招商银行", "code": "600036"}], "reason": "超预期"}],
        "bullish": {"directions": ["宽松"], "sectors": ["银行"], "stocks": []},
        "bearish": {"directions": [], "sectors": [], "stocks": []},
        "company_sina": [], "top5_bullish": [{"title": "招商银行业绩超预期", "reason": "确定性"}],
    })
    db.add_watch(conn, "600036", "招商银行")
    app = web.create_app(lambda: conn, QueryCache(ttl=1))
    return TestClient(app), conn


def test_insights_renders_top20_and_tags():
    client, _ = _setup()
    r = client.get("/insights")
    assert r.status_code == 200
    assert "招商银行业绩超预期" in r.text
    assert "利好" in r.text          # 情感 tag
    assert "自选" in r.text          # 自选股命中标记


def test_watchlist_page_and_add_remove():
    client, conn = _setup()
    r = client.get("/watchlist")
    assert "招商银行" in r.text
    r = client.post("/watchlist/add", data={"code": "688981", "name": "中芯国际", "aliases": "中芯"},
                    follow_redirects=True)
    assert "中芯国际" in r.text
    r = client.post("/watchlist/remove", data={"code": "688981"}, follow_redirects=True)
    assert "中芯国际" not in r.text
