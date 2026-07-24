import datetime

import pytest
from fastapi.testclient import TestClient

from ainews import db, web
from ainews.cache import QueryCache

CONFIG = {"initial_capital": 2_000_000}


@pytest.fixture(autouse=True)
def _no_network_quotes(monkeypatch):
    """默认阻断 quotes 模块的真实行情获取,测试内按需 monkeypatch 覆盖具体返回值。"""
    monkeypatch.setattr(web.quotes, "get_quotes", lambda codes: {})
    monkeypatch.setattr(web.quotes, "get_prices", lambda codes: {})


def _setup():
    conn = db.get_conn(":memory:")
    db.init_db(conn)
    db.open_position(conn, "600036", "招商银行", 100, 35.0, 3510.0,
                     datetime.datetime(2026, 7, 22, 9, 30))
    db.record_trade(conn, trade_at=datetime.datetime(2026, 7, 22, 9, 30), code="600036",
                    name="招商银行", side="buy", qty=100, price=35.0, amount=3500.0,
                    commission=5.0, transfer_fee=0.035, reason="利好信号(2源)", pnl=None)
    db.record_trade(conn, trade_at=datetime.datetime(2026, 7, 20, 10, 0), code="000001",
                    name="平安银行", side="sell", qty=200, price=12.5, amount=2500.0,
                    stamp_tax=1.25, commission=5.0, transfer_fee=0.025,
                    reason="止盈+10.0%", pnl=120.5)
    db.queue_pending_order(conn, created_at=datetime.datetime(2026, 7, 23, 8, 0), code="600519",
                           name="贵州茅台", side="buy", reason="利好信号(3源)", priority=90)
    app = web.create_app(lambda: conn, QueryCache(ttl=1), config=CONFIG)
    return TestClient(app), conn


def test_trading_page_with_quotes(monkeypatch):
    client, conn = _setup()
    monkeypatch.setattr(web.quotes, "get_prices", lambda codes: {"600036": 38.5})

    r = client.get("/trading")

    assert r.status_code == 200
    assert "招商银行" in r.text          # 持仓
    assert "贵州茅台" in r.text          # 待执行
    assert "止盈+10.0%" in r.text        # 交易记录原因
    assert "模拟盘假设" in r.text        # 免责声明
    assert "总资产" in r.text
    assert "38.50" in r.text            # 现价
    assert "pct-up" in r.text or "pct-down" in r.text  # 浮盈/实现盈亏染色


def test_trading_page_offline_quotes_never_500():
    """行情获取失败(默认 fixture 已模拟离线):页面仍 200,现价显示 '—'。"""
    client, conn = _setup()

    r = client.get("/trading")

    assert r.status_code == 200
    assert "招商银行" in r.text
    assert "—" in r.text


def test_trading_page_offline_quotes_raising_never_500(monkeypatch):
    client, conn = _setup()

    def _boom(codes):
        raise RuntimeError("network down")

    monkeypatch.setattr(web.quotes, "get_prices", _boom)

    r = client.get("/trading")

    assert r.status_code == 200
    assert "—" in r.text


def test_trading_page_no_positions_shows_empty_state():
    conn = db.get_conn(":memory:")
    db.init_db(conn)
    app = web.create_app(lambda: conn, QueryCache(ttl=1), config=CONFIG)
    client = TestClient(app)

    r = client.get("/trading")

    assert r.status_code == 200
    assert "暂无持仓" in r.text
    assert "暂无待执行订单" in r.text
    assert "暂无交易记录" in r.text
