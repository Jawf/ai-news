"""FastAPI Web 应用：服务端渲染新闻流 + JSON API + TTL 缓存。"""
import os
from typing import Callable

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ainews import db, quotes, stockref
from ainews.cache import QueryCache
from ainews.classifier import DEFAULT_RULES
from ainews.watch_match import annotate

_HERE = os.path.dirname(os.path.abspath(__file__))
PAGE_SIZE = 30


def create_app(conn_factory: Callable, cache: QueryCache,
               categories: list[str] | None = None, config: dict | None = None) -> FastAPI:
    app = FastAPI(title="ai-news")
    templates = Jinja2Templates(directory=os.path.join(_HERE, "templates"))
    app.mount("/static", StaticFiles(directory=os.path.join(_HERE, "static")), name="static")
    cats = categories or list(DEFAULT_RULES.keys()) + ["其他"]
    trading_config = config or {}

    def _query(source, category, date, page):
        key = f"{source}|{category}|{date}|{page}"
        def producer():
            return db.query_news(conn_factory(), source=source, category=category,
                                 date=date, limit=PAGE_SIZE, offset=(page - 1) * PAGE_SIZE)
        return cache.get_or_set(key, producer)

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request, source: str = "", category: str = "",
              date: str = "", page: int = 1):
        items = _query(source or None, category or None, date or None, page)
        return templates.TemplateResponse(request, "index.html", {
            "items": items, "categories": cats,
            "source": source, "category": category, "date": date, "page": page,
        })

    @app.get("/api/news")
    def api_news(source: str = "", category: str = "", date: str = "", page: int = 1):
        items = _query(source or None, category or None, date or None, page)
        return JSONResponse({"items": items, "page": page})

    @app.get("/insights", response_class=HTMLResponse)
    def insights(request: Request):
        def producer():
            payload = db.latest_analysis(conn_factory())
            if not payload:
                return None
            return annotate(payload, db.list_watch(conn_factory()))
        data = cache.get_or_set("insights", producer)
        watch_codes = {w["code"] for w in db.list_watch(conn_factory())}
        return templates.TemplateResponse(request, "insights.html", {
            "data": data, "watch_codes": watch_codes})

    @app.get("/watchlist", response_class=HTMLResponse)
    def watchlist_page(request: Request):
        conn = conn_factory()
        watch = db.list_watch(conn)
        payload = db.latest_analysis(conn)
        related = annotate(payload, db.list_watch(conn))["watch_related"] if payload else []
        related_by_code = {r["code"]: r for r in related}

        codes = [w["code"] for w in watch if w["code"]]
        try:
            live_quotes = quotes.get_quotes(codes) if codes else {}
        except Exception:
            live_quotes = {}

        enriched = []
        for w in watch:
            q = live_quotes.get(w["code"])
            change_pct = None
            price = None
            if q and q.get("prev_close"):
                price = q["price"]
                change_pct = (q["price"] - q["prev_close"]) / q["prev_close"] * 100
            rel = related_by_code.get(w["code"])
            items = rel["items"] if rel else []
            enriched.append({
                **w, "price": price, "change_pct": change_pct,
                "latest_sentiment": items[0]["sentiment"] if items else None,
                "related_count": len(items),
            })

        return templates.TemplateResponse(request, "watchlist.html", {
            "watch": enriched, "related": related})

    @app.post("/watchlist/add")
    def watchlist_add(code: str = Form(""), name: str = Form(""), aliases: str = Form(""),
                      next: str = Form("")):
        target = next if next.startswith("/") else "/watchlist"
        code, name = code.strip(), name.strip()
        if not code and not name:
            return RedirectResponse(target, status_code=303)
        alias_list = [a.strip() for a in aliases.split(",") if a.strip()]
        conn = conn_factory()
        resolved_code, resolved_name = stockref.resolve(conn, code=code or None, name=name or None)
        db.add_watch(conn, resolved_code, resolved_name, alias_list)
        return RedirectResponse(target, status_code=303)

    @app.post("/watchlist/remove")
    def watchlist_remove(code: str = Form(...)):
        db.remove_watch(conn_factory(), code.strip())
        return RedirectResponse("/watchlist", status_code=303)

    @app.get("/trading", response_class=HTMLResponse)
    def trading_page(request: Request):
        conn = conn_factory()
        initial_capital = trading_config.get("initial_capital", 2_000_000)
        cash = db.get_cash(conn, initial_capital)

        positions = db.list_positions(conn, status="holding")
        codes = [p["code"] for p in positions if p["code"]]
        try:
            prices = quotes.get_prices(codes) if codes else {}
        except Exception:
            prices = {}

        enriched_positions = []
        market_value = 0.0
        for p in positions:
            cost_price = p.get("cost_price") or 0
            price = prices.get(p["code"])
            if price is not None:
                mv = price * p["qty"]
                pnl_pct = ((price - cost_price) / cost_price * 100) if cost_price else None
            else:
                mv = cost_price * p["qty"]
                pnl_pct = None
            market_value += mv
            enriched_positions.append({**p, "price": price, "market_value": mv, "pnl_pct": pnl_pct})

        nav = cash + market_value
        profit_rate = ((nav - initial_capital) / initial_capital * 100) if initial_capital else 0.0
        realized_pnl = db.realized_pnl_total(conn)
        trades = db.list_trades(conn)
        total_fees = sum((t.get("stamp_tax") or 0) + (t.get("commission") or 0)
                        + (t.get("transfer_fee") or 0) for t in trades)

        return templates.TemplateResponse(request, "trading.html", {
            "cash": cash, "market_value": market_value, "nav": nav,
            "profit_rate": profit_rate, "realized_pnl": realized_pnl,
            "total_fees": total_fees, "positions": enriched_positions,
            "pending": db.list_pending_orders(conn), "trades": trades,
        })

    return app
