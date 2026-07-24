"""FastAPI Web 应用：服务端渲染新闻流 + JSON API + TTL 缓存。"""
import os
from typing import Callable

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ainews import db, stockref
from ainews.cache import QueryCache
from ainews.classifier import DEFAULT_RULES
from ainews.watch_match import annotate

_HERE = os.path.dirname(os.path.abspath(__file__))
PAGE_SIZE = 30


def create_app(conn_factory: Callable, cache: QueryCache,
               categories: list[str] | None = None) -> FastAPI:
    app = FastAPI(title="ai-news")
    templates = Jinja2Templates(directory=os.path.join(_HERE, "templates"))
    app.mount("/static", StaticFiles(directory=os.path.join(_HERE, "static")), name="static")
    cats = categories or list(DEFAULT_RULES.keys()) + ["其他"]

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
        return templates.TemplateResponse(request, "insights.html", {"data": data})

    @app.get("/watchlist", response_class=HTMLResponse)
    def watchlist_page(request: Request):
        conn = conn_factory()
        payload = db.latest_analysis(conn)
        related = annotate(payload, db.list_watch(conn))["watch_related"] if payload else []
        return templates.TemplateResponse(request, "watchlist.html", {
            "watch": db.list_watch(conn), "related": related})

    @app.post("/watchlist/add")
    def watchlist_add(code: str = Form(""), name: str = Form(""), aliases: str = Form("")):
        code, name = code.strip(), name.strip()
        if not code and not name:
            return RedirectResponse("/watchlist", status_code=303)
        alias_list = [a.strip() for a in aliases.split(",") if a.strip()]
        conn = conn_factory()
        resolved_code, resolved_name = stockref.resolve(conn, code=code or None, name=name or None)
        db.add_watch(conn, resolved_code, resolved_name, alias_list)
        return RedirectResponse("/watchlist", status_code=303)

    @app.post("/watchlist/remove")
    def watchlist_remove(code: str = Form(...)):
        db.remove_watch(conn_factory(), code.strip())
        return RedirectResponse("/watchlist", status_code=303)

    return app
