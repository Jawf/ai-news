import datetime
from ainews import db, trader

NOW = datetime.datetime(2026, 7, 23, 9, 35)

CONFIG = {
    "sim_initial_amount": 100000,
    "stamp_tax_rate": 0.0005,
    "commission_rate": 0.00025,
    "commission_min": 5.0,
    "take_profit": 0.10,
    "stop_loss": 0.08,
    "min_sources_to_buy": 2,
    "max_positions": 20,
}


def _conn():
    c = db.get_conn(":memory:")
    db.init_db(c)
    return c


def _cfg(**overrides):
    cfg = dict(CONFIG)
    cfg.update(overrides)
    return cfg


# --- 买入 ---

def test_buy_bullish_stock_with_enough_sources():
    c = _conn()
    payload = {
        "top20": [{"stocks": [{"name": "招商银行", "code": "600036"}],
                   "sources": ["雪球", "财联社"]}],
        "bullish": {"stocks": [{"name": "招商银行", "code": "600036"}]},
        "bearish": {"stocks": []},
    }
    prices = {"600036": 35.0}
    result = trader.run_trading(CONFIG, c, payload=payload, prices=prices, now=NOW)

    assert result["bought"] == ["600036"]
    positions = db.list_positions(c, status="holding")
    assert len(positions) == 1
    pos = positions[0]
    assert pos["qty"] % 100 == 0 and pos["qty"] > 0
    trades = db.list_trades(c)
    assert len(trades) == 1
    trade = trades[0]
    assert trade["side"] == "buy"
    assert trade["reason"] == "利好信号(2源)"
    assert trade["commission"] >= 5.0


def test_no_rebuy_when_already_holding():
    c = _conn()
    db.open_position(c, "600036", "招商银行", 100, 30.0, 3007.5, NOW)
    payload = {
        "top20": [{"stocks": [{"name": "招商银行", "code": "600036"}],
                   "sources": ["雪球", "财联社"]}],
        "bullish": {"stocks": [{"name": "招商银行", "code": "600036"}]},
        "bearish": {"stocks": []},
    }
    prices = {"600036": 31.0}  # 位于止盈(33.0)/止损(27.6)区间内，不触发平仓
    result = trader.run_trading(CONFIG, c, payload=payload, prices=prices, now=NOW)

    assert result["bought"] == []
    assert len(db.list_positions(c, status="holding")) == 1  # 未新开仓


def test_skip_when_sources_below_min():
    c = _conn()
    payload = {
        "top20": [],  # 从未出现在 top20 -> sources_count = 1 < min(2)
        "bullish": {"stocks": [{"name": "招商银行", "code": "600036"}]},
        "bearish": {"stocks": []},
    }
    prices = {"600036": 35.0}
    result = trader.run_trading(CONFIG, c, payload=payload, prices=prices, now=NOW)

    assert result["bought"] == []
    assert db.list_positions(c, status="holding") == []


def test_skip_when_price_missing():
    c = _conn()
    payload = {
        "top20": [{"stocks": [{"name": "招商银行", "code": "600036"}],
                   "sources": ["雪球", "财联社"]}],
        "bullish": {"stocks": [{"name": "招商银行", "code": "600036"}]},
        "bearish": {"stocks": []},
    }
    result = trader.run_trading(CONFIG, c, payload=payload, prices={}, now=NOW)

    assert result["bought"] == []
    assert db.list_positions(c, status="holding") == []
    assert any(s.get("code") == "600036" for s in result["skipped"])


def test_max_positions_keeps_top_n_by_sources():
    c = _conn()
    payload = {
        "top20": [
            {"stocks": [{"name": "股票A", "code": "600001"}], "sources": ["s1", "s2", "s3", "s4"]},
            {"stocks": [{"name": "股票B", "code": "600002"}], "sources": ["s1", "s2", "s3"]},
            {"stocks": [{"name": "股票C", "code": "600003"}], "sources": ["s1", "s2"]},
        ],
        "bullish": {"stocks": [
            {"name": "股票A", "code": "600001"},
            {"name": "股票B", "code": "600002"},
            {"name": "股票C", "code": "600003"},
        ]},
        "bearish": {"stocks": []},
    }
    prices = {"600001": 10.0, "600002": 10.0, "600003": 10.0}
    result = trader.run_trading(_cfg(max_positions=2), c, payload=payload, prices=prices, now=NOW)

    assert set(result["bought"]) == {"600001", "600002"}
    assert "600003" not in result["bought"]


# --- 卖出：利空信号 ---

def test_sell_on_bearish_signal_computes_pnl_and_closes_position():
    c = _conn()
    db.open_position(c, "600036", "招商银行", 100, 30.0, 3007.5, NOW)
    payload = {
        "top20": [],
        "bullish": {"stocks": []},
        "bearish": {"stocks": [{"name": "招商银行", "code": "600036"}]},
    }
    prices = {"600036": 32.0}
    result = trader.run_trading(CONFIG, c, payload=payload, prices=prices, now=NOW)

    assert result["sold"] == ["600036"]
    assert db.list_positions(c, status="holding") == []
    trade = db.list_trades(c)[0]
    assert trade["side"] == "sell"
    assert trade["reason"] == "利空信号"
    assert trade["stamp_tax"] > 0
    expected_amount = 100 * 32.0
    expected_stamp = expected_amount * CONFIG["stamp_tax_rate"]
    expected_commission = max(expected_amount * CONFIG["commission_rate"], CONFIG["commission_min"])
    expected_pnl = (expected_amount - expected_stamp - expected_commission) - 3007.5
    assert trade["pnl"] == expected_pnl


# --- 止盈 / 止损（check_stops） ---

def test_check_stops_take_profit_and_stop_loss():
    c = _conn()
    db.open_position(c, "600010", "股票甲", 100, 10.0, 1005.0, NOW)  # 止盈线 11.0
    db.open_position(c, "600020", "股票乙", 100, 20.0, 2005.0, NOW)  # 止损线 18.4
    prices = {"600010": 11.5, "600020": 18.0}
    result = trader.check_stops(CONFIG, c, prices=prices, now=NOW)

    assert set(result["sold"]) == {"600010", "600020"}
    assert db.list_positions(c, status="holding") == []
    trades = {t["code"]: t for t in db.list_trades(c)}
    assert "止盈" in trades["600010"]["reason"]
    assert "止损" in trades["600020"]["reason"]


def test_check_stops_holds_when_within_band():
    c = _conn()
    db.open_position(c, "600010", "股票甲", 100, 10.0, 1005.0, NOW)
    prices = {"600010": 10.5}  # 未触发止盈(11.0)/止损(9.2)
    result = trader.check_stops(CONFIG, c, prices=prices, now=NOW)

    assert result["sold"] == []
    assert len(db.list_positions(c, status="holding")) == 1


# --- 卖出腾出仓位供本轮买入 ---

def test_sells_free_slots_for_buys_in_same_run():
    c = _conn()
    db.open_position(c, "600030", "甲股", 100, 10.0, 1005.0, NOW)
    payload = {
        "top20": [{"stocks": [{"name": "乙股", "code": "600040"}], "sources": ["s1", "s2"]}],
        "bullish": {"stocks": [{"name": "乙股", "code": "600040"}]},
        "bearish": {"stocks": [{"name": "甲股", "code": "600030"}]},
    }
    prices = {"600030": 9.0, "600040": 10.0}
    result = trader.run_trading(_cfg(max_positions=1), c, payload=payload, prices=prices, now=NOW)

    assert result["sold"] == ["600030"]
    assert result["bought"] == ["600040"]
    holding_codes = {p["code"] for p in db.list_positions(c, status="holding")}
    assert holding_codes == {"600040"}


# --- 无最新分析快照 ---

def test_run_trading_skips_when_no_analysis():
    c = _conn()
    result = trader.run_trading(CONFIG, c, payload=None, now=NOW)
    assert result == {"skipped": "no analysis"}


# --- code 缺失时通过 stockref 反查 ---

def test_resolves_missing_code_via_stockref():
    c = _conn()
    db.bulk_upsert_stock_ref(c, [("600036", "招商银行")])  # 预置，避免触发 akshare 加载
    payload = {
        "top20": [{"stocks": [{"name": "招商银行", "code": ""}], "sources": ["s1", "s2"]}],
        "bullish": {"stocks": [{"name": "招商银行", "code": ""}]},
        "bearish": {"stocks": []},
    }
    prices = {"600036": 35.0}
    result = trader.run_trading(CONFIG, c, payload=payload, prices=prices, now=NOW)
    assert result["bought"] == ["600036"]


def test_skips_unresolvable_non_a_share():
    c = _conn()
    db.bulk_upsert_stock_ref(c, [("600036", "招商银行")])  # 预置，避免触发 akshare 加载
    payload = {
        "top20": [{"stocks": [{"name": "某港股", "code": ""}], "sources": ["s1", "s2"]}],
        "bullish": {"stocks": [{"name": "某港股", "code": ""}]},
        "bearish": {"stocks": []},
    }
    result = trader.run_trading(CONFIG, c, payload=payload, prices={}, now=NOW)
    assert result["bought"] == []
    assert db.list_positions(c, status="holding") == []
