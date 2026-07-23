from ainews import db, pipeline
from ainews.models import NewsItem


SRC = {"id": "xq", "name": "雪球", "endpoint": "x", "mapping": {}}


def test_run_source_inserts_and_counts():
    conn = db.get_conn(":memory:"); db.init_db(conn)
    def fake_fetch(cfg, client=None):
        return [NewsItem(source="xq", title="降准", external_id="1"),
                NewsItem(source="xq", title="上涨", external_id="2")]
    res = pipeline.run_source(conn, SRC, fetch=fake_fetch)
    assert res["fetched"] == 2 and res["new"] == 2 and res["status"] == "ok"
    # 再跑一次全部重复
    res2 = pipeline.run_source(conn, SRC, fetch=fake_fetch)
    assert res2["new"] == 0


def test_run_source_isolates_failure():
    conn = db.get_conn(":memory:"); db.init_db(conn)
    def boom(cfg, client=None):
        raise RuntimeError("network down")
    res = pipeline.run_source(conn, SRC, fetch=boom)
    assert res["status"] == "error"
    assert res["new"] == 0  # 不抛异常，记录错误
