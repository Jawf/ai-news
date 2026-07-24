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


def test_record_trade_stores_transfer_fee():
    c = _conn()
    db.record_trade(c, trade_at=datetime.datetime(2026, 7, 23, 9, 30), code="600036",
                    name="招商银行", side="buy", qty=100, price=35.0, amount=3500.0,
                    commission=5.0, transfer_fee=0.035, reason="利好信号(2源)", pnl=None)
    row = db.list_trades(c)[0]
    assert row["transfer_fee"] == 0.035


def test_last_trade_returns_most_recent_by_side():
    c = _conn()
    db.record_trade(c, trade_at=datetime.datetime(2026, 7, 20, 9, 30), code="600036",
                    name="招商银行", side="sell", qty=100, price=30.0, amount=3000.0,
                    reason="止损", pnl=-10.0)
    db.record_trade(c, trade_at=datetime.datetime(2026, 7, 22, 9, 30), code="600036",
                    name="招商银行", side="sell", qty=100, price=31.0, amount=3100.0,
                    reason="止损", pnl=-5.0)
    row = db.last_trade(c, "600036", "sell")
    assert row["trade_at"].startswith("2026-07-22")
    assert db.last_trade(c, "600036", "buy") is None
    assert db.last_trade(c, "999999", "sell") is None


# --- 待办单（pending_orders） ---

def test_queue_and_list_pending_orders_ordered_by_priority():
    c = _conn()
    db.queue_pending_order(c, created_at=datetime.datetime(2026, 7, 23, 8, 0), code="600001",
                           name="股票A", side="buy", reason="利好信号", priority=60)
    db.queue_pending_order(c, created_at=datetime.datetime(2026, 7, 23, 8, 0), code="600002",
                           name="股票B", side="buy", reason="利好信号", priority=80)
    rows = db.list_pending_orders(c, side="buy")
    assert [r["code"] for r in rows] == ["600002", "600001"]  # 高优先级在前


def test_has_pending_order_true_after_queue():
    c = _conn()
    assert db.has_pending_order(c, "600001", "buy") is False
    db.queue_pending_order(c, created_at=datetime.datetime(2026, 7, 23, 8, 0), code="600001",
                           name="股票A", side="buy", reason="利好信号")
    assert db.has_pending_order(c, "600001", "buy") is True
    assert db.has_pending_order(c, "600001", "sell") is False


def test_delete_pending_order_removes_it():
    c = _conn()
    oid = db.queue_pending_order(c, created_at=datetime.datetime(2026, 7, 23, 8, 0), code="600001",
                                 name="股票A", side="buy", reason="利好信号")
    db.delete_pending_order(c, oid)
    assert db.list_pending_orders(c) == []


# --- 现金账户（account） ---

def test_get_cash_lazily_initializes_from_initial():
    c = _conn()
    assert db.get_cash(c, 2_000_000) == 2_000_000
    # 二次读取沿用已建行的余额，不会被 initial 覆盖
    db.adjust_cash(c, -100_000)
    assert db.get_cash(c, 2_000_000) == 1_900_000


def test_adjust_cash_accumulates_deltas():
    c = _conn()
    db.get_cash(c, 1_000_000)
    db.adjust_cash(c, -50_000)
    new_balance = db.adjust_cash(c, 20_000)
    assert new_balance == 970_000
