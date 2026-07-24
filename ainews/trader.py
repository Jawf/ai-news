"""模拟交易引擎：由 AI 洞察快照驱动的自动买卖（利好买/利空卖/止盈止损）。

- BUY: 最新快照 bullish.stocks 中来源数 >= min_sources_to_buy、未持仓、可解析为 A 股代码的信号，
  按来源数降序优先，每笔用 sim_initial_amount 现价买入、数量向下取整为 100 股整数倍。
- SELL（全仓卖出）：① 出现在 bearish.stocks；② 价格 >= 成本*(1+take_profit) 止盈；
  ③ 价格 <= 成本*(1-stop_loss) 止损。
- 费用：印花税仅卖出收，佣金买卖双向收（有最低值）。
"""
import datetime

from ainews import db, quotes, stockref


def _clean(v) -> str:
    return (v or "").strip()


def _is_a_share(conn, code: str) -> bool:
    """A 股代码：6 位数字，或能在 stock_ref 全量映射表中查到。"""
    if not code:
        return False
    if code.isdigit() and len(code) == 6:
        return True
    _, ref_name = db.find_stock(conn, code=code)
    return bool(ref_name)


def _sources_count_for_stock(code: str, name: str, top20: list[dict]) -> int:
    """统计 top20 中提及该股票的条目的（去重后）信源数；从未出现则记 1。"""
    matched: set[str] = set()
    for entry in top20:
        for es in entry.get("stocks") or []:
            e_code = _clean(es.get("code"))
            e_name = _clean(es.get("name"))
            same = (code and e_code and code == e_code) or (name and e_name and name == e_name)
            if same:
                matched.update(entry.get("sources") or [])
                break
    return len(matched) if matched else 1


def _resolve_bullish_candidates(conn, bullish_stocks: list[dict], top20: list[dict],
                                 min_sources: int) -> tuple[list[dict], list[dict]]:
    """把 payload 里的利好个股解析为可交易候选（未过滤持仓/资金/价格）。"""
    candidates, skipped = [], []
    for stock in bullish_stocks:
        name = _clean(stock.get("name"))
        code = _clean(stock.get("code"))
        if not code:
            resolved_code, resolved_name = stockref.resolve(conn, name=name)
            code = _clean(resolved_code)
            name = name or _clean(resolved_name)
        if not _is_a_share(conn, code):
            skipped.append({"code": code, "name": name, "reason": "非A股或代码无法解析"})
            continue
        sources_count = _sources_count_for_stock(code, name, top20)
        if sources_count < min_sources:
            skipped.append({"code": code, "name": name,
                            "reason": f"来源不足({sources_count}<{min_sources})"})
            continue
        candidates.append({"code": code, "name": name, "sources_count": sources_count})
    return candidates, skipped


def _evaluate_sell_reason(position: dict, price: float, take_profit: float, stop_loss: float,
                          bearish_codes: set, bearish_names: set) -> str | None:
    code, name = position["code"], position.get("name") or ""
    if code in bearish_codes or name in bearish_names:
        return "利空信号"
    cost = position["cost_price"]
    if not cost:
        return None
    change_pct = (price / cost - 1) * 100
    if price >= cost * (1 + take_profit):
        return f"止盈+{change_pct:.1f}%"
    if price <= cost * (1 - stop_loss):
        return f"止损{change_pct:.1f}%"
    return None


def _run_sells(config: dict, conn, prices: dict[str, float], now,
               bearish_codes: set, bearish_names: set) -> list[str]:
    take_profit = config.get("take_profit", 0.10)
    stop_loss = config.get("stop_loss", 0.08)
    stamp_tax_rate = config.get("stamp_tax_rate", 0.0005)
    commission_rate = config.get("commission_rate", 0.00025)
    commission_min = config.get("commission_min", 5.0)

    sold = []
    for pos in db.list_positions(conn, status="holding"):
        code = pos["code"]
        price = prices.get(code)
        if price is None:
            continue
        reason = _evaluate_sell_reason(pos, price, take_profit, stop_loss,
                                       bearish_codes, bearish_names)
        if not reason:
            continue
        qty = pos["qty"]
        amount = qty * price
        stamp_tax = amount * stamp_tax_rate
        commission = max(amount * commission_rate, commission_min)
        pnl = (amount - stamp_tax - commission) - pos["cost_amount"]
        db.record_trade(conn, trade_at=now, code=code, name=pos.get("name"), side="sell",
                        qty=qty, price=price, amount=amount, stamp_tax=stamp_tax,
                        commission=commission, reason=reason, pnl=pnl)
        db.close_position(conn, pos["id"])
        sold.append(code)
    return sold


def _run_buys(config: dict, conn, candidates: list[dict], prices: dict[str, float],
             slots: int, now) -> tuple[list[str], list[dict]]:
    sim_amount = config.get("sim_initial_amount", 100000)
    commission_rate = config.get("commission_rate", 0.00025)
    commission_min = config.get("commission_min", 5.0)

    bought, skipped = [], []
    for cand in candidates:
        if slots <= 0:
            skipped.append({"code": cand["code"], "name": cand["name"], "reason": "已达持仓上限"})
            continue
        code, name, sources_count = cand["code"], cand["name"], cand["sources_count"]
        price = prices.get(code)
        if price is None:
            skipped.append({"code": code, "name": name, "reason": "无法获取现价"})
            continue
        qty = int(sim_amount // price // 100) * 100
        if qty == 0:
            skipped.append({"code": code, "name": name, "reason": "资金不足100股"})
            continue
        amount = qty * price
        commission = max(amount * commission_rate, commission_min)
        cost_amount = amount + commission
        db.open_position(conn, code, name, qty, price, cost_amount, now)
        db.record_trade(conn, trade_at=now, code=code, name=name, side="buy",
                        qty=qty, price=price, amount=amount, stamp_tax=0.0,
                        commission=commission, reason=f"利好信号({sources_count}源)", pnl=None)
        bought.append(code)
        slots -= 1
    return bought, skipped


def run_trading(config: dict, conn, payload: dict | None = None,
                prices: dict[str, float] | None = None, now=None) -> dict:
    if payload is None:
        payload = db.latest_analysis(conn)
    if payload is None:
        return {"skipped": "no analysis"}
    now = now or datetime.datetime.now()
    min_sources = config.get("min_sources_to_buy", 2)
    max_positions = config.get("max_positions", 20)

    top20 = payload.get("top20") or []
    bullish_stocks = (payload.get("bullish") or {}).get("stocks") or []
    bearish_stocks = (payload.get("bearish") or {}).get("stocks") or []
    bearish_codes = {_clean(s.get("code")) for s in bearish_stocks if _clean(s.get("code"))}
    bearish_names = {_clean(s.get("name")) for s in bearish_stocks if _clean(s.get("name"))}

    held_before = db.list_positions(conn, status="holding")
    held_codes_before = {p["code"] for p in held_before}

    raw_candidates, skipped = _resolve_bullish_candidates(conn, bullish_stocks, top20, min_sources)

    needed_codes = held_codes_before | {c["code"] for c in raw_candidates}
    if prices is None:
        prices = quotes.get_prices(sorted(needed_codes))

    sold = _run_sells(config, conn, prices, now, bearish_codes, bearish_names)
    held_codes_after = held_codes_before - set(sold)

    buy_candidates = []
    for c in raw_candidates:
        if c["code"] in held_codes_after:
            skipped.append({"code": c["code"], "name": c["name"], "reason": "已持仓"})
            continue
        buy_candidates.append(c)
    buy_candidates.sort(key=lambda c: -c["sources_count"])

    slots = max_positions - len(held_codes_after)
    bought, buy_skipped = _run_buys(config, conn, buy_candidates, prices, slots, now)
    skipped.extend(buy_skipped)

    return {"bought": bought, "sold": sold, "skipped": skipped}


def check_stops(config: dict, conn, prices: dict[str, float] | None = None, now=None) -> dict:
    """仅巡检止盈②/止损③（不涉及利空①，无需最新分析快照），供整点巡检调用。"""
    now = now or datetime.datetime.now()
    held_codes = {p["code"] for p in db.list_positions(conn, status="holding")}
    if prices is None:
        prices = quotes.get_prices(sorted(held_codes))
    sold = _run_sells(config, conn, prices, now, bearish_codes=set(), bearish_names=set())
    return {"sold": sold}
