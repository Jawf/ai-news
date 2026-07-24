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


def test_insights_renders_multi_source_corroboration():
    conn = db.get_conn(":memory:")
    db.init_db(conn)
    db.save_analysis_run(conn, __import__("datetime").datetime.now(), "ok", payload={
        "top20": [
            {"title": "央行全面降准", "source": "xq", "importance": 95,
             "sentiment": "利好", "sectors": ["银行"], "stocks": [],
             "reason": "流动性宽松", "sources": ["雪球", "财联社", "金十"]},
            {"title": "无信源标注的旧快照条目", "source": "cls", "importance": 60,
             "sentiment": "中性", "sectors": [], "stocks": [], "reason": "占位"},
        ],
        "bullish": {"directions": [], "sectors": [], "stocks": []},
        "bearish": {"directions": [], "sectors": [], "stocks": []},
        "company_sina": [], "top5_bullish": [],
    })
    app = web.create_app(lambda: conn, QueryCache(ttl=1))
    client = TestClient(app)
    r = client.get("/insights")
    assert r.status_code == 200
    assert "3源" in r.text
    assert "雪球" in r.text and "财联社" in r.text and "金十" in r.text
    assert "无信源标注的旧快照条目" in r.text


def test_watchlist_page_and_add_remove():
    client, conn = _setup()
    r = client.get("/watchlist")
    assert "招商银行" in r.text
    r = client.post("/watchlist/add", data={"code": "688981", "name": "中芯国际", "aliases": "中芯"},
                    follow_redirects=True)
    assert "中芯国际" in r.text
    r = client.post("/watchlist/remove", data={"code": "688981"}, follow_redirects=True)
    assert "中芯国际" not in r.text


def test_watchlist_add_reverse_lookup_by_name_only():
    """只填名称,代码从预置的 stock_ref 全 A 股映射表反查补全（不触网络）。"""
    from ainews import db as db_mod
    client, conn = _setup()
    db_mod.bulk_upsert_stock_ref(conn, [("601318", "中国平安")])
    r = client.post("/watchlist/add", data={"name": "中国平安"}, follow_redirects=True)
    assert "中国平安" in r.text
    assert "601318" in r.text


def test_watchlist_add_reverse_lookup_by_code_only():
    """只填代码,名称从预置的 stock_ref 反查补全。"""
    from ainews import db as db_mod
    client, conn = _setup()
    db_mod.bulk_upsert_stock_ref(conn, [("000002", "万科A")])
    r = client.post("/watchlist/add", data={"code": "000002"}, follow_redirects=True)
    assert "万科A" in r.text
    assert "000002" in r.text


def test_watchlist_add_both_empty_is_noop():
    client, conn = _setup()
    before = len(db.list_watch(conn))
    r = client.post("/watchlist/add", data={"code": "", "name": ""}, follow_redirects=True)
    assert r.status_code == 200
    assert len(db.list_watch(conn)) == before
