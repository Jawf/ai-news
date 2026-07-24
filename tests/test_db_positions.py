import datetime
from ainews import db


def _conn():
    c = db.get_conn(":memory:")
    db.init_db(c)
    return c


def test_open_position_and_list_holding():
    c = _conn()
    pid = db.open_position(c, "600036", "招商银行", 100, 35.0, 3510.0,
                            datetime.datetime(2026, 7, 23, 9, 30))
    assert isinstance(pid, int)
    rows = db.list_positions(c, status="holding")
    assert len(rows) == 1
    assert rows[0]["code"] == "600036"
    assert rows[0]["qty"] == 100
    assert rows[0]["cost_price"] == 35.0
    assert rows[0]["cost_amount"] == 3510.0
    assert rows[0]["status"] == "holding"


def test_close_position_removes_from_holding_list():
    c = _conn()
    pid = db.open_position(c, "600036", "招商银行", 100, 35.0, 3510.0,
                            datetime.datetime(2026, 7, 23, 9, 30))
    db.close_position(c, pid)
    assert db.list_positions(c, status="holding") == []
    closed = db.list_positions(c, status="closed")
    assert len(closed) == 1 and closed[0]["id"] == pid


def test_record_trade_and_list_trades_order():
    c = _conn()
    db.record_trade(c, trade_at=datetime.datetime(2026, 7, 23, 9, 30), code="600036",
                    name="招商银行", side="buy", qty=100, price=35.0, amount=3500.0,
                    stamp_tax=0.0, commission=5.0, reason="利好信号(2源)", pnl=None)
    db.record_trade(c, trade_at=datetime.datetime(2026, 7, 23, 10, 0), code="600036",
                    name="招商银行", side="sell", qty=100, price=38.5, amount=3850.0,
                    stamp_tax=1.925, commission=5.0, reason="止盈+10.0%", pnl=338.075)
    rows = db.list_trades(c)
    assert len(rows) == 2
    assert rows[0]["side"] == "sell"  # 最新在前
    assert rows[1]["side"] == "buy"


def test_realized_pnl_total_sums_sell_pnl_only():
    c = _conn()
    db.record_trade(c, trade_at=datetime.datetime(2026, 7, 23, 9, 30), code="600036",
                    name="招商银行", side="buy", qty=100, price=35.0, amount=3500.0,
                    commission=5.0, reason="利好信号(2源)", pnl=None)
    assert db.realized_pnl_total(c) == 0.0
    db.record_trade(c, trade_at=datetime.datetime(2026, 7, 23, 10, 0), code="600036",
                    name="招商银行", side="sell", qty=100, price=38.5, amount=3850.0,
                    stamp_tax=1.925, commission=5.0, reason="止盈+10.0%", pnl=338.075)
    assert db.realized_pnl_total(c) == 338.075
