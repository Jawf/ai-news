import datetime
from ainews import db, trader

# 2026-07-23 是周四（开市日）；07-22 周三（T+1 合规的前一交易日）；
# 07-24 周五；07-25 周六（闭市）。
NOW = datetime.datetime(2026, 7, 23, 9, 35)          # 开市（上午时段）
PREV_DAY = datetime.datetime(2026, 7, 22, 9, 35)     # 前一日开仓 -> 满足 T+1
CLOSED_PRE_MARKET = datetime.datetime(2026, 7, 23, 8, 0)   # 盘前，闭市
WEEKEND = datetime.datetime(2026, 7, 25, 9, 35)      # 周六，闭市

CONFIG = {
    "sim_initial_amount": 100000,
    "stamp_tax_rate": 0.0005,
    "commission_rate": 0.00025,
    "commission_min": 5.0,
    "take_profit": 0.10,
    "stop_loss": 0.08,
    "min_sources_to_buy": 2,
    "max_positions": 20,
    "initial_capital": 2_000_000,
    "reentry_cooldown_days": 3,
    "transfer_fee_rate": 0.00001,
}


def _conn():
    c = db.get_conn(":memory:")
    db.init_db(c)
    return c


def _cfg(**overrides):
    cfg = dict(CONFIG)
    cfg.update(overrides)
    return cfg


def _q(price, high=None, low=None, prev_close=None):
    """构造一条行情：未显式指定的 high/low/prev_close 缺省等于 price（不触发涨跌停约束）。"""
    return {
        "price": price,
        "high": high if high is not None else price,
        "low": low if low is not None else price,
        "prev_close": prev_close if prev_close is not None else price,
    }


# --- 买入 ---

def test_buy_bullish_stock_with_enough_sources():
    c = _conn()
    payload = {
        "top20": [{"stocks": [{"name": "招商银行", "code": "600036"}],
                   "sources": ["雪球", "财联社"]}],
        "bullish": {"stocks": [{"name": "招商银行", "code": "600036"}]},
        "bearish": {"stocks": []},
    }
    quotes = {"600036": _q(35.0)}
    result = trader.run_trading(CONFIG, c, payload=payload, quotes=quotes, now=NOW)

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
    quotes = {"600036": _q(31.0)}  # 位于止盈(33.0)/止损(27.6)区间内，不触发平仓
    result = trader.run_trading(CONFIG, c, payload=payload, quotes=quotes, now=NOW)

    assert result["bought"] == []
    assert len(db.list_positions(c, status="holding")) == 1  # 未新开仓


def test_skip_when_sources_below_min():
    c = _conn()
    payload = {
        "top20": [],  # 从未出现在 top20 -> sources_count = 1 < min(2)
        "bullish": {"stocks": [{"name": "招商银行", "code": "600036"}]},
        "bearish": {"stocks": []},
    }
    quotes = {"600036": _q(35.0)}
    result = trader.run_trading(CONFIG, c, payload=payload, quotes=quotes, now=NOW)

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
    result = trader.run_trading(CONFIG, c, payload=payload, quotes={}, now=NOW)

    assert result["bought"] == []
    assert db.list_positions(c, status="holding") == []
    assert any(s.get("code") == "600036" for s in result["skipped"])


def test_max_positions_keeps_top_n_by_priority():
    """买入优先级现按 top20 命中条目的最高 importance 排序（不再是来源数）。"""
    c = _conn()
    payload = {
        "top20": [
            {"stocks": [{"name": "股票A", "code": "600001"}],
             "sources": ["s1", "s2", "s3", "s4"], "importance": 90},
            {"stocks": [{"name": "股票B", "code": "600002"}],
             "sources": ["s1", "s2", "s3"], "importance": 70},
            {"stocks": [{"name": "股票C", "code": "600003"}],
             "sources": ["s1", "s2"], "importance": 50},
        ],
        "bullish": {"stocks": [
            {"name": "股票A", "code": "600001"},
            {"name": "股票B", "code": "600002"},
            {"name": "股票C", "code": "600003"},
        ]},
        "bearish": {"stocks": []},
    }
    quotes = {"600001": _q(10.0), "600002": _q(10.0), "600003": _q(10.0)}
    result = trader.run_trading(_cfg(max_positions=2), c, payload=payload, quotes=quotes, now=NOW)

    assert set(result["bought"]) == {"600001", "600002"}  # importance 90/70 优先于 50
    assert "600003" not in result["bought"]


# --- 卖出：利空信号（T+1 生效） ---

def test_sell_on_bearish_signal_computes_pnl_and_closes_position():
    c = _conn()
    db.open_position(c, "600036", "招商银行", 100, 30.0, 3007.5, PREV_DAY)
    payload = {
        "top20": [],
        "bullish": {"stocks": []},
        "bearish": {"stocks": [{"name": "招商银行", "code": "600036"}]},
    }
    quotes = {"600036": _q(32.0)}
    result = trader.run_trading(CONFIG, c, payload=payload, quotes=quotes, now=NOW)

    assert result["sold"] == ["600036"]
    assert db.list_positions(c, status="holding") == []
    trade = db.list_trades(c)[0]
    assert trade["side"] == "sell"
    assert trade["reason"] == "利空信号"
    assert trade["stamp_tax"] > 0
    assert trade["transfer_fee"] > 0
    expected_amount = 100 * 32.0
    expected_stamp = expected_amount * CONFIG["stamp_tax_rate"]
    expected_commission = max(expected_amount * CONFIG["commission_rate"], CONFIG["commission_min"])
    expected_transfer = expected_amount * CONFIG["transfer_fee_rate"]
    expected_pnl = (expected_amount - expected_stamp - expected_commission - expected_transfer) - 3007.5
    assert trade["pnl"] == expected_pnl


# --- T+1（当日开仓不可卖出，这是本次整改的核心行为变更） ---

def test_t1_blocks_sell_on_position_opened_today():
    c = _conn()
    db.open_position(c, "600036", "招商银行", 100, 30.0, 3007.5, NOW)  # 今日开仓
    payload = {
        "top20": [],
        "bullish": {"stocks": []},
        "bearish": {"stocks": [{"name": "招商银行", "code": "600036"}]},
    }
    quotes = {"600036": _q(32.0)}
    result = trader.run_trading(CONFIG, c, payload=payload, quotes=quotes, now=NOW)

    assert result["sold"] == []
    assert len(db.list_positions(c, status="holding")) == 1
    assert any(s.get("code") == "600036" and s.get("reason") == "T+1" for s in result["skipped"])


def test_t1_allows_sell_on_position_opened_prior_day():
    c = _conn()
    db.open_position(c, "600036", "招商银行", 100, 30.0, 3007.5, PREV_DAY)
    payload = {
        "top20": [],
        "bullish": {"stocks": []},
        "bearish": {"stocks": [{"name": "招商银行", "code": "600036"}]},
    }
    quotes = {"600036": _q(32.0)}
    result = trader.run_trading(CONFIG, c, payload=payload, quotes=quotes, now=NOW)

    assert result["sold"] == ["600036"]
    assert db.list_positions(c, status="holding") == []


# --- 止盈 / 止损（run_patrol，按当日最高/最低价触线） ---

def test_run_patrol_take_profit_and_stop_loss():
    c = _conn()
    db.open_position(c, "600010", "股票甲", 100, 10.0, 1005.0, PREV_DAY)  # 止盈线 11.0
    db.open_position(c, "600020", "股票乙", 100, 20.0, 2005.0, PREV_DAY)  # 止损线 18.4
    quotes = {
        "600010": _q(11.3, high=11.5, low=11.0, prev_close=10.0),
        "600020": _q(18.3, high=18.3, low=17.5, prev_close=20.0),
    }
    result = trader.run_patrol(CONFIG, c, quotes=quotes, now=NOW)

    assert set(result["sold"]) == {"600010", "600020"}
    assert db.list_positions(c, status="holding") == []
    trades = {t["code"]: t for t in db.list_trades(c)}
    assert "止盈" in trades["600010"]["reason"]
    assert "止损" in trades["600020"]["reason"]


def test_run_patrol_holds_when_within_band():
    c = _conn()
    db.open_position(c, "600010", "股票甲", 100, 10.0, 1005.0, PREV_DAY)
    quotes = {"600010": _q(10.5, high=10.5, low=10.5, prev_close=10.0)}  # 未触发止盈(11.0)/止损(9.2)
    result = trader.run_patrol(CONFIG, c, quotes=quotes, now=NOW)

    assert result["sold"] == []
    assert len(db.list_positions(c, status="holding")) == 1


def test_take_profit_fills_at_tp_line_not_day_high():
    """止盈按止盈线价成交，不是按当日最高价（高价可能只是盘中脉冲，非可实际成交价）。"""
    c = _conn()
    db.open_position(c, "600010", "股票甲", 100, 10.0, 1005.0, PREV_DAY)
    quotes = {"600010": _q(10.5, high=11.2, low=10.3, prev_close=10.0)}
    result = trader.run_patrol(CONFIG, c, quotes=quotes, now=NOW)

    assert result["sold"] == ["600010"]
    trade = db.list_trades(c)[0]
    assert trade["price"] == 11.0
    amount = 100 * 11.0
    stamp = amount * CONFIG["stamp_tax_rate"]
    commission = max(amount * CONFIG["commission_rate"], CONFIG["commission_min"])
    transfer = amount * CONFIG["transfer_fee_rate"]
    expected_pnl = (amount - stamp - commission - transfer) - 1005.0
    assert trade["pnl"] == expected_pnl


# --- 卖出腾出仓位供本轮买入 ---

def test_sells_free_slots_for_buys_in_same_run():
    c = _conn()
    db.open_position(c, "600030", "甲股", 100, 10.0, 1005.0, PREV_DAY)
    payload = {
        "top20": [{"stocks": [{"name": "乙股", "code": "600040"}], "sources": ["s1", "s2"]}],
        "bullish": {"stocks": [{"name": "乙股", "code": "600040"}]},
        "bearish": {"stocks": [{"name": "甲股", "code": "600030"}]},
    }
    quotes = {"600030": _q(9.0), "600040": _q(10.0)}
    result = trader.run_trading(_cfg(max_positions=1), c, payload=payload, quotes=quotes, now=NOW)

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
    quotes = {"600036": _q(35.0)}
    result = trader.run_trading(CONFIG, c, payload=payload, quotes=quotes, now=NOW)
    assert result["bought"] == ["600036"]


def test_skips_unresolvable_non_a_share():
    c = _conn()
    db.bulk_upsert_stock_ref(c, [("600036", "招商银行")])  # 预置，避免触发 akshare 加载
    payload = {
        "top20": [{"stocks": [{"name": "某港股", "code": ""}], "sources": ["s1", "s2"]}],
        "bullish": {"stocks": [{"name": "某港股", "code": ""}]},
        "bearish": {"stocks": []},
    }
    result = trader.run_trading(CONFIG, c, payload=payload, quotes={}, now=NOW)
    assert result["bought"] == []
    assert db.list_positions(c, status="holding") == []


# --- 时段门控 + 延迟成交（闭市只登记待办单，不按陈旧价成交） ---

def test_run_trading_queues_buy_when_closed_pre_market():
    c = _conn()
    payload = {
        "top20": [{"stocks": [{"name": "招商银行", "code": "600036"}],
                   "sources": ["雪球", "财联社"]}],
        "bullish": {"stocks": [{"name": "招商银行", "code": "600036"}]},
        "bearish": {"stocks": []},
    }
    result = trader.run_trading(CONFIG, c, payload=payload, now=CLOSED_PRE_MARKET)

    assert result["bought"] == []
    assert result["queued_buy"] == ["600036"]
    assert db.list_positions(c, status="holding") == []
    pending = db.list_pending_orders(c, side="buy")
    assert len(pending) == 1 and pending[0]["code"] == "600036"


def test_run_trading_queues_buy_when_closed_weekend():
    c = _conn()
    payload = {
        "top20": [{"stocks": [{"name": "招商银行", "code": "600036"}],
                   "sources": ["雪球", "财联社"]}],
        "bullish": {"stocks": [{"name": "招商银行", "code": "600036"}]},
        "bearish": {"stocks": []},
    }
    result = trader.run_trading(CONFIG, c, payload=payload, now=WEEKEND)

    assert result["queued_buy"] == ["600036"]
    assert db.list_positions(c, status="holding") == []


def test_run_trading_queues_sell_when_closed_and_t1_ok():
    c = _conn()
    db.open_position(c, "600036", "招商银行", 100, 30.0, 3007.5, PREV_DAY)
    payload = {
        "top20": [],
        "bullish": {"stocks": []},
        "bearish": {"stocks": [{"name": "招商银行", "code": "600036"}]},
    }
    result = trader.run_trading(CONFIG, c, payload=payload, now=CLOSED_PRE_MARKET)

    assert result["queued_sell"] == ["600036"]
    pending = db.list_pending_orders(c, side="sell")
    assert len(pending) == 1 and pending[0]["code"] == "600036"


def test_run_trading_does_not_queue_sell_blocked_by_t1_when_closed():
    c = _conn()
    db.open_position(c, "600036", "招商银行", 100, 30.0, 3007.5, CLOSED_PRE_MARKET)  # 今日已开仓
    payload = {
        "top20": [],
        "bullish": {"stocks": []},
        "bearish": {"stocks": [{"name": "招商银行", "code": "600036"}]},
    }
    result = trader.run_trading(CONFIG, c, payload=payload, now=CLOSED_PRE_MARKET)

    assert result["queued_sell"] == []
    assert db.list_pending_orders(c, side="sell") == []
    assert any(s.get("reason") == "T+1" for s in result["skipped"])


def test_run_patrol_executes_pending_buy_in_session():
    c = _conn()
    db.queue_pending_order(c, created_at=NOW, code="600036", name="招商银行",
                           side="buy", reason="利好信号(2源)", priority=80)
    quotes = {"600036": _q(35.0)}
    result = trader.run_patrol(CONFIG, c, quotes=quotes, now=NOW)

    assert result["bought"] == ["600036"]
    assert db.list_pending_orders(c) == []
    assert len(db.list_positions(c, status="holding")) == 1


def test_run_patrol_is_noop_when_closed():
    c = _conn()
    db.queue_pending_order(c, created_at=NOW, code="600036", name="招商银行",
                           side="buy", reason="利好信号(2源)")
    result = trader.run_patrol(CONFIG, c, now=CLOSED_PRE_MARKET)

    assert result == {"skipped": "closed"}
    assert len(db.list_pending_orders(c)) == 1  # 待办单未被消费


def test_run_patrol_expires_stale_pending_buy():
    c = _conn()
    stale_created = datetime.datetime(2026, 7, 20, 8, 0)  # 距 NOW 已超过 1 个交易日
    db.queue_pending_order(c, created_at=stale_created, code="600036", name="招商银行",
                           side="buy", reason="利好信号(2源)")
    quotes = {"600036": _q(35.0)}
    result = trader.run_patrol(CONFIG, c, quotes=quotes, now=NOW)

    assert result["bought"] == []
    assert db.list_pending_orders(c) == []
    assert any(s.get("reason") == "已过期" for s in result["skipped"])


# --- 涨跌停约束 ---

def test_buy_blocked_at_limit_up_stays_pending_then_fills_when_price_retreats():
    c = _conn()
    payload = {
        "top20": [{"stocks": [{"name": "招商银行", "code": "600036"}],
                   "sources": ["雪球", "财联社"]}],
        "bullish": {"stocks": [{"name": "招商银行", "code": "600036"}]},
        "bearish": {"stocks": []},
    }
    quotes = {"600036": _q(11.0, prev_close=10.0)}  # 10% 板块，涨停价附近，无卖盘
    result = trader.run_trading(CONFIG, c, payload=payload, quotes=quotes, now=NOW)

    assert result["bought"] == []
    assert any(s.get("reason") == "涨停无卖盘" for s in result["skipped"])
    assert len(db.list_pending_orders(c, side="buy")) == 1  # 留待巡检重试

    retreat_quotes = {"600036": _q(10.5, prev_close=10.0)}
    patrol_result = trader.run_patrol(CONFIG, c, quotes=retreat_quotes, now=NOW)
    assert patrol_result["bought"] == ["600036"]
    assert db.list_pending_orders(c) == []


def test_buy_fills_directly_when_not_at_limit():
    c = _conn()
    payload = {
        "top20": [{"stocks": [{"name": "招商银行", "code": "600036"}],
                   "sources": ["雪球", "财联社"]}],
        "bullish": {"stocks": [{"name": "招商银行", "code": "600036"}]},
        "bearish": {"stocks": []},
    }
    quotes = {"600036": _q(10.5, prev_close=10.0)}
    result = trader.run_trading(CONFIG, c, payload=payload, quotes=quotes, now=NOW)

    assert result["bought"] == ["600036"]


def test_sell_blocked_at_limit_down_retries_next_patrol():
    c = _conn()
    db.open_position(c, "600010", "股票甲", 100, 10.0, 1005.0, PREV_DAY)
    blocked_quotes = {"600010": _q(9.0, high=9.0, low=8.9, prev_close=10.0)}  # 止损触发但跌停无买盘
    result = trader.run_patrol(CONFIG, c, quotes=blocked_quotes, now=NOW)

    assert result["sold"] == []
    assert any(s.get("reason") == "跌停无买盘" for s in result["skipped"])
    assert len(db.list_positions(c, status="holding")) == 1

    recovered_quotes = {"600010": _q(9.3, high=9.3, low=9.1, prev_close=10.0)}
    retry_result = trader.run_patrol(CONFIG, c, quotes=recovered_quotes, now=NOW)
    assert retry_result["sold"] == ["600010"]


# --- 现金账户 / NAV ---

def test_cash_insufficient_skips_second_buy():
    c = _conn()
    cfg = _cfg(initial_capital=6000)
    payload = {
        "top20": [
            {"stocks": [{"name": "股票甲", "code": "600001"}], "sources": ["s1", "s2"]},
            {"stocks": [{"name": "股票乙", "code": "600002"}], "sources": ["s1", "s2"]},
        ],
        "bullish": {"stocks": [
            {"name": "股票甲", "code": "600001"},
            {"name": "股票乙", "code": "600002"},
        ]},
        "bearish": {"stocks": []},
    }
    quotes = {"600001": _q(50.0), "600002": _q(50.0)}
    result = trader.run_trading(cfg, c, payload=payload, quotes=quotes, now=NOW)

    assert result["bought"] == ["600001"]
    assert any(s.get("code") == "600002" and s.get("reason") == "现金不足" for s in result["skipped"])


def test_sell_credits_cash_back():
    c = _conn()
    cfg = _cfg(initial_capital=6000)
    db.get_cash(c, cfg["initial_capital"])
    db.open_position(c, "600001", "股票甲", 100, 50.0, 5005.05, PREV_DAY)
    db.adjust_cash(c, -5005.05)
    cash_before = db.get_cash(c, cfg["initial_capital"])

    sell_payload = {"top20": [], "bullish": {"stocks": []},
                    "bearish": {"stocks": [{"name": "股票甲", "code": "600001"}]}}
    result = trader.run_trading(cfg, c, payload=sell_payload, quotes={"600001": _q(52.0)}, now=NOW)

    assert result["sold"] == ["600001"]
    cash_after = db.get_cash(c, cfg["initial_capital"])
    assert cash_after > cash_before


# --- 矛盾信号 / 再入场冷却 ---

def test_contradiction_signal_takes_no_action():
    c = _conn()
    payload = {
        "top20": [{"stocks": [{"name": "招商银行", "code": "600036"}], "sources": ["s1", "s2"]}],
        "bullish": {"stocks": [{"name": "招商银行", "code": "600036"}]},
        "bearish": {"stocks": [{"name": "招商银行", "code": "600036"}]},
    }
    result = trader.run_trading(CONFIG, c, payload=payload, quotes={"600036": _q(35.0)}, now=NOW)

    assert result["bought"] == []
    assert result["sold"] == []
    assert any(s.get("code") == "600036" and s.get("reason") == "信号矛盾" for s in result["skipped"])


def test_reentry_cooldown_blocks_rebuy_after_sell():
    c = _conn()
    db.open_position(c, "600036", "招商银行", 100, 30.0, 3007.5, PREV_DAY)
    sell_payload = {"top20": [], "bullish": {"stocks": []},
                    "bearish": {"stocks": [{"name": "招商银行", "code": "600036"}]}}
    trader.run_trading(CONFIG, c, payload=sell_payload, quotes={"600036": _q(32.0)}, now=NOW)
    assert db.list_positions(c, status="holding") == []

    rebuy_payload = {
        "top20": [{"stocks": [{"name": "招商银行", "code": "600036"}], "sources": ["s1", "s2"]}],
        "bullish": {"stocks": [{"name": "招商银行", "code": "600036"}]},
        "bearish": {"stocks": []},
    }
    result = trader.run_trading(CONFIG, c, payload=rebuy_payload, quotes={"600036": _q(33.0)}, now=NOW)

    assert result["bought"] == []
    assert any(s.get("code") == "600036" and s.get("reason") == "冷却期未满" for s in result["skipped"])


def test_reentry_allowed_after_cooldown_expires():
    c = _conn()
    db.open_position(c, "600036", "招商银行", 100, 30.0, 3007.5, PREV_DAY)
    sell_payload = {"top20": [], "bullish": {"stocks": []},
                    "bearish": {"stocks": [{"name": "招商银行", "code": "600036"}]}}
    trader.run_trading(CONFIG, c, payload=sell_payload, quotes={"600036": _q(32.0)}, now=NOW)

    later = NOW + datetime.timedelta(days=4)  # 超过冷却期(3天)，2026-07-27 周一
    rebuy_payload = {
        "top20": [{"stocks": [{"name": "招商银行", "code": "600036"}], "sources": ["s1", "s2"]}],
        "bullish": {"stocks": [{"name": "招商银行", "code": "600036"}]},
        "bearish": {"stocks": []},
    }
    result = trader.run_trading(CONFIG, c, payload=rebuy_payload, quotes={"600036": _q(33.0)}, now=later)
    assert result["bought"] == ["600036"]


# --- 板块特殊规则 + 费用 ---

def test_688_min_lot_is_200_shares():
    c = _conn()
    payload = {
        "top20": [{"stocks": [{"name": "科创股", "code": "688001"}], "sources": ["s1", "s2"]}],
        "bullish": {"stocks": [{"name": "科创股", "code": "688001"}]},
        "bearish": {"stocks": []},
    }
    quotes = {"688001": _q(800.0)}
    result = trader.run_trading(CONFIG, c, payload=payload, quotes=quotes, now=NOW)

    assert result["bought"] == ["688001"]
    pos = db.list_positions(c, status="holding")[0]
    assert pos["qty"] == 200


def test_st_name_never_bought():
    c = _conn()
    payload = {
        "top20": [{"stocks": [{"name": "*ST锐电", "code": "600001"}], "sources": ["s1", "s2"]}],
        "bullish": {"stocks": [{"name": "*ST锐电", "code": "600001"}]},
        "bearish": {"stocks": []},
    }
    result = trader.run_trading(CONFIG, c, payload=payload, quotes={"600001": _q(10.0)}, now=NOW)

    assert result["bought"] == []
    assert any(s.get("code") == "600001" and s.get("reason") == "ST不买入" for s in result["skipped"])


def test_transfer_fee_recorded_on_buy_trade_and_included_in_cost_amount():
    c = _conn()
    payload = {
        "top20": [{"stocks": [{"name": "招商银行", "code": "600036"}], "sources": ["s1", "s2"]}],
        "bullish": {"stocks": [{"name": "招商银行", "code": "600036"}]},
        "bearish": {"stocks": []},
    }
    result = trader.run_trading(CONFIG, c, payload=payload, quotes={"600036": _q(35.0)}, now=NOW)

    assert result["bought"] == ["600036"]
    trade = db.list_trades(c)[0]
    assert trade["transfer_fee"] > 0
    expected_amount = trade["qty"] * trade["price"]
    expected_cost_amount = expected_amount + trade["commission"] + trade["transfer_fee"]
    pos = db.list_positions(c, status="holding")[0]
    assert pos["cost_amount"] == expected_cost_amount
