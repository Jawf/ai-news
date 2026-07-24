"""模拟交易引擎：由 AI 洞察快照驱动的自动买卖（利好自动买/利空止盈止损自动卖）。

- BUY: 最新快照 bullish.stocks 中来源数 >= min_sources_to_buy、未持仓、可解析为 A 股代码、
  非 ST、未在同批利空信号中矛盾、未处于卖出冷却期的信号，按 top20 中该股最高 importance
  （未出现则 50）降序优先，每笔用 sim_initial_amount/现金 现价买入。
- SELL（全仓卖出）：① 出现在 bearish.stocks（run_trading 评估）；② 当日最高价 >= 成本*(1+take_profit)
  止盈（run_patrol 评估，按止盈线价成交）；③ 当日最低价 <= 成本*(1-stop_loss) 止损（run_patrol 评估，
  按 min(止损线价, 现价) 成交）。
- T+1：opened_at 与 now 同日的持仓不可卖出（A 股 T+1 规则），任何卖出路径均受此约束。
- 时段门控：仅 A 股交易时段（工作日 09:30-11:30 / 13:00-15:00）可真正成交。run_trading 在
  非交易时段把买卖决策落地为 pending_orders 待办单，不按收盘/盘前的陈旧价成交；run_patrol
  （整点巡检）开市时先清算待办单再巡检止盈止损，闭市时 no-op。
  已知局限：未接入法定节假日日历，仅按"工作日+时段"判断，法定节假日仍会被当作开市日。
- 涨跌停约束：涨停（价格触及板块涨停价 * 0.995 即视为无卖盘）不可买入；跌停（价格触及板块
  跌停价 * 1.005 即视为无买盘）不可卖出。板块判定：688/30 开头 20%，名称含 ST 5%，其余 10%。
- 费用：印花税仅卖出收，佣金买卖双向收（有最低值），过户费买卖双向收（按成交额计）。
"""
import datetime

from ainews import db, quotes as quotes_mod, stockref

_MORNING_START = datetime.time(9, 30)
_MORNING_END = datetime.time(11, 30)
_AFTERNOON_START = datetime.time(13, 0)
_AFTERNOON_END = datetime.time(15, 0)


def _clean(v) -> str:
    return (v or "").strip()


def _in_session(now: datetime.datetime) -> bool:
    """A 股交易时段：工作日 09:30-11:30 / 13:00-15:00。

    已知局限：未接入法定节假日日历，仅按"工作日+时段"判断，法定节假日仍会被当作开市日。
    """
    if now.weekday() >= 5:  # 5=周六 6=周日
        return False
    t = now.time()
    return (_MORNING_START <= t <= _MORNING_END) or (_AFTERNOON_START <= t <= _AFTERNOON_END)


def _is_a_share(conn, code: str) -> bool:
    """A 股代码：6 位数字，或能在 stock_ref 全量映射表中查到。"""
    if not code:
        return False
    if code.isdigit() and len(code) == 6:
        return True
    _, ref_name = db.find_stock(conn, code=code)
    return bool(ref_name)


def _is_st(name: str) -> bool:
    return "ST" in (name or "").upper()


def _board_limit(code: str, name: str) -> float:
    """涨跌停幅度：688/创业板(30 开头) 20%；名称含 ST 5%；其余 10%。"""
    if code.startswith("688") or code.startswith("30"):
        return 0.20
    if _is_st(name):
        return 0.05
    return 0.10


def _buy_blocked_by_limit(price: float, prev_close: float | None, limit: float) -> bool:
    """涨停无卖盘：价格触及/逼近涨停价即不可买入。"""
    if not prev_close:
        return False
    return price >= prev_close * (1 + limit) * 0.995


def _sell_blocked_by_limit(price: float, prev_close: float | None, limit: float) -> bool:
    """跌停无买盘：价格触及/逼近跌停价即不可卖出。"""
    if not prev_close:
        return False
    return price <= prev_close * (1 - limit) * 1.005


def _t1_blocked(position: dict, now: datetime.datetime) -> bool:
    """T+1：持仓开仓日与 now 同一自然日则不可卖出。"""
    opened_at = position.get("opened_at")
    if not opened_at:
        return False
    opened_date = datetime.datetime.fromisoformat(opened_at).date()
    return opened_date >= now.date()


def _in_cooldown(conn, code: str, now: datetime.datetime, cooldown_days: int) -> bool:
    """再入场冷却：code 最近一次卖出距今不足 cooldown_days 天则不可再买入。"""
    last_sell = db.last_trade(conn, code, "sell")
    if not last_sell:
        return False
    sell_date = datetime.datetime.fromisoformat(last_sell["trade_at"]).date()
    return (now.date() - sell_date).days < cooldown_days


def _resolve_stock_list(conn, stocks: list[dict]) -> list[dict]:
    """把 payload 里的个股条目解析出 code/name（code 缺失时经 stockref 反查）。"""
    out = []
    for stock in stocks:
        name = _clean(stock.get("name"))
        code = _clean(stock.get("code"))
        if not code:
            resolved_code, resolved_name = stockref.resolve(conn, name=name)
            code = _clean(resolved_code)
            name = name or _clean(resolved_name)
        out.append({"code": code, "name": name})
    return out


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


def _priority_for_stock(code: str, name: str, top20: list[dict]) -> float:
    """买入优先级 = 提及该股票的 top20 条目中最高 importance；从未出现则记 50（中性默认）。"""
    best = None
    for entry in top20:
        matched = False
        for es in entry.get("stocks") or []:
            e_code = _clean(es.get("code"))
            e_name = _clean(es.get("name"))
            if (code and e_code and code == e_code) or (name and e_name and name == e_name):
                matched = True
                break
        if matched:
            importance = entry.get("importance")
            if importance is not None:
                best = importance if best is None else max(best, importance)
    return best if best is not None else 50


def _resolve_bullish_candidates(conn, bullish_resolved: list[dict], top20: list[dict],
                                 min_sources: int, contradiction_codes: set,
                                 contradiction_names: set) -> tuple[list[dict], list[dict]]:
    """把已解析的利好个股筛为可交易候选（未过滤持仓/资金/价格），按优先级携带排序依据。"""
    candidates, skipped = [], []
    for stock in bullish_resolved:
        code, name = stock["code"], stock["name"]
        if code in contradiction_codes or (name and name in contradiction_names):
            skipped.append({"code": code, "name": name, "reason": "信号矛盾"})
            continue
        if not _is_a_share(conn, code):
            skipped.append({"code": code, "name": name, "reason": "非A股或代码无法解析"})
            continue
        if _is_st(name):
            skipped.append({"code": code, "name": name, "reason": "ST不买入"})
            continue
        sources_count = _sources_count_for_stock(code, name, top20)
        if sources_count < min_sources:
            skipped.append({"code": code, "name": name,
                            "reason": f"来源不足({sources_count}<{min_sources})"})
            continue
        priority = _priority_for_stock(code, name, top20)
        candidates.append({"code": code, "name": name, "sources_count": sources_count,
                           "priority": priority})
    return candidates, skipped


def _try_buy(config: dict, conn, code: str, name: str | None, quote: dict,
            now: datetime.datetime, reason: str) -> tuple[bool, str | None]:
    """尝试买入。成功返回 (True, None)；失败返回 (False, 跳过原因)。"""
    if _is_st(name):
        return False, "ST不买入"

    price = quote["price"]
    prev_close = quote.get("prev_close")
    board_limit = _board_limit(code, name or "")
    if _buy_blocked_by_limit(price, prev_close, board_limit):
        return False, "涨停无卖盘"

    initial_capital = config.get("initial_capital", 2_000_000)
    cash = db.get_cash(conn, initial_capital)

    sim_amount = config.get("sim_initial_amount", 100000)
    commission_rate = config.get("commission_rate", 0.00025)
    commission_min = config.get("commission_min", 5.0)
    transfer_fee_rate = config.get("transfer_fee_rate", 0.00001)

    # 688 简化：仍按 100 股步进取整，仅把下限抬到 200 股（不模拟"200 股后 +1 股递增"的精细规则）
    min_qty = 200 if code.startswith("688") else 100
    budget = min(sim_amount, cash)
    qty = int(budget // price // 100) * 100
    if qty < min_qty:
        qty = min_qty  # 高价股：sim_amount 买不够一手，但现金若够则至少买一手

    amount = qty * price
    commission = max(amount * commission_rate, commission_min)
    transfer_fee = amount * transfer_fee_rate
    cost_amount = amount + commission + transfer_fee
    if cost_amount > cash:
        return False, "现金不足"

    db.open_position(conn, code, name, qty, price, cost_amount, now)
    db.record_trade(conn, trade_at=now, code=code, name=name, side="buy",
                    qty=qty, price=price, amount=amount, stamp_tax=0.0,
                    commission=commission, transfer_fee=transfer_fee, reason=reason, pnl=None)
    db.adjust_cash(conn, -cost_amount)
    return True, None


def _try_sell(config: dict, conn, position: dict, price: float, reason: str,
             now: datetime.datetime, quote: dict | None) -> tuple[bool, str | None]:
    """尝试卖出。成功返回 (True, None)；失败返回 (False, 跳过原因)。"""
    code, name = position["code"], position.get("name") or ""
    if _t1_blocked(position, now):
        return False, "T+1"

    prev_close = quote.get("prev_close") if quote else None
    board_limit = _board_limit(code, name)
    if _sell_blocked_by_limit(price, prev_close, board_limit):
        return False, "跌停无买盘"

    initial_capital = config.get("initial_capital", 2_000_000)
    db.get_cash(conn, initial_capital)  # 确保账户已惰性初始化，adjust_cash 才有行可改

    qty = position["qty"]
    amount = qty * price
    stamp_tax = amount * config.get("stamp_tax_rate", 0.0005)
    commission = max(amount * config.get("commission_rate", 0.00025),
                     config.get("commission_min", 5.0))
    transfer_fee = amount * config.get("transfer_fee_rate", 0.00001)
    net = amount - stamp_tax - commission - transfer_fee
    pnl = net - position["cost_amount"]

    db.record_trade(conn, trade_at=now, code=code, name=position.get("name"), side="sell",
                    qty=qty, price=price, amount=amount, stamp_tax=stamp_tax,
                    commission=commission, transfer_fee=transfer_fee, reason=reason, pnl=pnl)
    db.close_position(conn, position["id"])
    db.adjust_cash(conn, net)
    return True, None


def _run_bearish_sells(config: dict, conn, quotes: dict, now: datetime.datetime,
                       bearish_codes: set, bearish_names: set, contradiction_codes: set,
                       contradiction_names: set) -> tuple[list[str], list[dict]]:
    """利空信号卖出（仅 run_trading 调用，需要最新分析快照的利空清单）。"""
    sold, skipped = [], []
    for pos in db.list_positions(conn, status="holding"):
        code, name = pos["code"], pos.get("name") or ""
        if not (code in bearish_codes or name in bearish_names):
            continue
        if code in contradiction_codes or (name and name in contradiction_names):
            skipped.append({"code": code, "name": name, "reason": "信号矛盾"})
            continue
        quote = quotes.get(code)
        if quote is None:
            skipped.append({"code": code, "name": name, "reason": "无法获取现价"})
            continue
        ok, why = _try_sell(config, conn, pos, quote["price"], "利空信号", now, quote)
        if ok:
            sold.append(code)
        else:
            skipped.append({"code": code, "name": name, "reason": why})
            if why == "跌停无买盘" and not db.has_pending_order(conn, code, "sell"):
                db.queue_pending_order(conn, created_at=now, code=code, name=name, side="sell",
                                       reason="利空信号", priority=0)
    return sold, skipped


def _run_stop_sells(config: dict, conn, quotes: dict,
                    now: datetime.datetime) -> tuple[list[str], list[dict]]:
    """止盈（按当日最高价触线，按止盈线价成交）/ 止损（按当日最低价触线，按 min(止损线价,现价) 成交）。

    仅 run_patrol（整点巡检）调用，与利空信号卖出无关，不涉及最新分析快照。
    """
    take_profit = config.get("take_profit", 0.10)
    stop_loss = config.get("stop_loss", 0.08)
    sold, skipped = [], []
    for pos in db.list_positions(conn, status="holding"):
        code, name = pos["code"], pos.get("name") or ""
        quote = quotes.get(code)
        if quote is None:
            continue
        cost = pos["cost_price"]
        if not cost:
            continue
        price = quote["price"]
        high = quote.get("high", price)
        low = quote.get("low", price)
        tp_line = cost * (1 + take_profit)
        sl_line = cost * (1 - stop_loss)

        fill_price, reason = None, None
        if high >= tp_line:
            fill_price = tp_line
            reason = f"止盈+{(tp_line / cost - 1) * 100:.1f}%"
        elif low <= sl_line:
            fill_price = min(sl_line, price)
            reason = f"止损{(fill_price / cost - 1) * 100:.1f}%"
        if reason is None:
            continue

        ok, why = _try_sell(config, conn, pos, fill_price, reason, now, quote)
        if ok:
            sold.append(code)
        else:
            skipped.append({"code": code, "name": name, "reason": why})
    return sold, skipped


def _run_buys_in_session(config: dict, conn, candidates: list[dict], quotes: dict,
                         slots: int, now: datetime.datetime) -> tuple[list[str], list[dict]]:
    bought, skipped = [], []
    for cand in candidates:
        code, name = cand["code"], cand["name"]
        if slots <= 0:
            skipped.append({"code": code, "name": name, "reason": "已达持仓上限"})
            continue
        quote = quotes.get(code)
        if quote is None:
            skipped.append({"code": code, "name": name, "reason": "无法获取现价"})
            continue
        ok, why = _try_buy(config, conn, code, name, quote, now,
                           reason=f"利好信号({cand['sources_count']}源)")
        if ok:
            bought.append(code)
            slots -= 1
        else:
            skipped.append({"code": code, "name": name, "reason": why})
            if why == "涨停无卖盘" and not db.has_pending_order(conn, code, "buy"):
                db.queue_pending_order(conn, created_at=now, code=code, name=name, side="buy",
                                       reason=f"利好信号({cand['sources_count']}源)",
                                       priority=cand["priority"])
    return bought, skipped


def run_trading(config: dict, conn, payload: dict | None = None,
                quotes: dict[str, dict] | None = None, now=None) -> dict:
    """信号驱动的买卖决策：开市时直接成交，闭市时把决策落地为 pending_orders 待办单。"""
    if payload is None:
        payload = db.latest_analysis(conn)
    if payload is None:
        return {"skipped": "no analysis"}
    now = now or datetime.datetime.now()
    min_sources = config.get("min_sources_to_buy", 2)
    max_positions = config.get("max_positions", 20)
    cooldown_days = config.get("reentry_cooldown_days", 3)

    top20 = payload.get("top20") or []
    bullish_stocks = (payload.get("bullish") or {}).get("stocks") or []
    bearish_stocks = (payload.get("bearish") or {}).get("stocks") or []

    bullish_resolved = _resolve_stock_list(conn, bullish_stocks)
    bearish_resolved = _resolve_stock_list(conn, bearish_stocks)
    bearish_codes = {s["code"] for s in bearish_resolved if s["code"]}
    bearish_names = {s["name"] for s in bearish_resolved if s["name"]}
    bullish_codes = {s["code"] for s in bullish_resolved if s["code"]}
    bullish_names = {s["name"] for s in bullish_resolved if s["name"]}
    contradiction_codes = bullish_codes & bearish_codes
    contradiction_names = bullish_names & bearish_names

    held_before = db.list_positions(conn, status="holding")
    held_codes_before = {p["code"] for p in held_before}

    raw_candidates, skipped = _resolve_bullish_candidates(
        conn, bullish_resolved, top20, min_sources, contradiction_codes, contradiction_names)

    if _in_session(now):
        needed_codes = held_codes_before | {c["code"] for c in raw_candidates}
        if quotes is None:
            quotes = quotes_mod.get_quotes(sorted(needed_codes))

        sold, sell_skipped = _run_bearish_sells(config, conn, quotes, now, bearish_codes,
                                                bearish_names, contradiction_codes,
                                                contradiction_names)
        skipped.extend(sell_skipped)
        held_codes_after = held_codes_before - set(sold)

        buy_candidates = []
        for c in raw_candidates:
            if c["code"] in held_codes_after:
                skipped.append({"code": c["code"], "name": c["name"], "reason": "已持仓"})
                continue
            if _in_cooldown(conn, c["code"], now, cooldown_days):
                skipped.append({"code": c["code"], "name": c["name"], "reason": "冷却期未满"})
                continue
            buy_candidates.append(c)
        buy_candidates.sort(key=lambda c: -c["priority"])

        slots = max_positions - len(held_codes_after)
        bought, buy_skipped = _run_buys_in_session(config, conn, buy_candidates, quotes,
                                                   slots, now)
        skipped.extend(buy_skipped)
        return {"bought": bought, "sold": sold, "skipped": skipped}

    # 闭市：不按陈旧价成交，把决策落地为待办单，开市巡检（run_patrol）时再清算
    queued_sell, queued_buy = [], []
    for pos in held_before:
        code, name = pos["code"], pos.get("name") or ""
        if not (code in bearish_codes or name in bearish_names):
            continue
        if code in contradiction_codes or (name and name in contradiction_names):
            skipped.append({"code": code, "name": name, "reason": "信号矛盾"})
            continue
        if _t1_blocked(pos, now):
            skipped.append({"code": code, "name": name, "reason": "T+1"})
            continue
        if db.has_pending_order(conn, code, "sell"):
            continue
        db.queue_pending_order(conn, created_at=now, code=code, name=name, side="sell",
                               reason="利空信号", priority=0)
        queued_sell.append(code)

    for c in raw_candidates:
        code, name = c["code"], c["name"]
        if code in held_codes_before:
            skipped.append({"code": code, "name": name, "reason": "已持仓"})
            continue
        if _in_cooldown(conn, code, now, cooldown_days):
            skipped.append({"code": code, "name": name, "reason": "冷却期未满"})
            continue
        if db.has_pending_order(conn, code, "buy"):
            continue
        db.queue_pending_order(conn, created_at=now, code=code, name=name, side="buy",
                               reason=f"利好信号({c['sources_count']}源)", priority=c["priority"])
        queued_buy.append(code)

    return {"bought": [], "sold": [], "queued_buy": queued_buy, "queued_sell": queued_sell,
            "skipped": skipped}


def run_patrol(config: dict, conn, quotes: dict[str, dict] | None = None, now=None) -> dict:
    """整点巡检：开市时先清算 pending_orders 待办单（按买入优先级排序），再评估止盈止损；
    闭市时 no-op。"""
    now = now or datetime.datetime.now()
    if not _in_session(now):
        return {"skipped": "closed"}

    skipped: list[dict] = []
    pending = db.list_pending_orders(conn)
    live_pending = []
    for order in pending:
        if order["side"] == "buy":
            created_date = datetime.datetime.fromisoformat(order["created_at"]).date()
            if created_date < (now.date() - datetime.timedelta(days=1)):
                db.delete_pending_order(conn, order["id"])
                skipped.append({"code": order["code"], "name": order["name"], "reason": "已过期"})
                continue
        live_pending.append(order)

    sell_orders = [o for o in live_pending if o["side"] == "sell"]
    buy_orders = sorted([o for o in live_pending if o["side"] == "buy"],
                        key=lambda o: -(o["priority"] or 0))

    held_positions = db.list_positions(conn, status="holding")
    positions_by_code = {p["code"]: p for p in held_positions}
    held_codes = set(positions_by_code)
    needed_codes = held_codes | {o["code"] for o in sell_orders} | {o["code"] for o in buy_orders}
    if quotes is None:
        quotes = quotes_mod.get_quotes(sorted(needed_codes))

    max_positions = config.get("max_positions", 20)
    executed_sells: list[str] = []
    for order in sell_orders:
        pos = positions_by_code.get(order["code"])
        if pos is None:  # 已通过其他路径平仓（如手工干预），清理陈旧待办单
            db.delete_pending_order(conn, order["id"])
            continue
        quote = quotes.get(order["code"])
        if quote is None:
            skipped.append({"code": order["code"], "name": order["name"], "reason": "无法获取现价"})
            continue
        ok, why = _try_sell(config, conn, pos, quote["price"], order["reason"], now, quote)
        if ok:
            executed_sells.append(order["code"])
            db.delete_pending_order(conn, order["id"])
            held_codes.discard(order["code"])
        else:
            skipped.append({"code": order["code"], "name": order["name"], "reason": why})
            # 涨跌停/无现价：留在待办单里，下次巡检重试

    executed_buys: list[str] = []
    for order in buy_orders:
        if len(held_codes) >= max_positions:
            skipped.append({"code": order["code"], "name": order["name"], "reason": "已达持仓上限"})
            continue
        quote = quotes.get(order["code"])
        if quote is None:
            skipped.append({"code": order["code"], "name": order["name"], "reason": "无法获取现价"})
            continue
        ok, why = _try_buy(config, conn, order["code"], order["name"], quote, now, order["reason"])
        if ok:
            executed_buys.append(order["code"])
            db.delete_pending_order(conn, order["id"])
            held_codes.add(order["code"])
        else:
            skipped.append({"code": order["code"], "name": order["name"], "reason": why})
            if why == "现金不足":
                db.delete_pending_order(conn, order["id"])  # 现金短期内不会自愈，丢弃等下次分析重新决策
            # 涨停/持仓已满：留在待办单里，下次巡检重试

    stop_sold, stop_skipped = _run_stop_sells(config, conn, quotes, now)
    skipped.extend(stop_skipped)

    return {"bought": executed_buys, "sold": executed_sells + stop_sold, "skipped": skipped}
