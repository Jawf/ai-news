import datetime
from ainews import db


def _conn():
    c = db.get_conn(":memory:")
    db.init_db(c)
    return c


def test_save_and_latest_analysis():
    c = _conn()
    t = datetime.datetime(2026, 7, 23, 8, 0)
    db.save_analysis_run(c, t, "error", payload=None, error="boom")
    db.save_analysis_run(c, t, "ok", payload={"top20": [{"title": "降准"}]})
    latest = db.latest_analysis(c)
    assert latest["top20"][0]["title"] == "降准"


def test_latest_analysis_none_when_empty():
    assert db.latest_analysis(_conn()) is None


def test_watchlist_crud():
    c = _conn()
    assert db.add_watch(c, "688981", "中芯国际", aliases=["中芯"]) is True
    assert db.add_watch(c, "688981", "中芯国际") is False  # 重复 code
    rows = db.list_watch(c)
    assert rows[0]["name"] == "中芯国际"
    assert rows[0]["aliases"] == ["中芯"]
    assert db.remove_watch(c, "688981") is True
    assert db.list_watch(c) == []
