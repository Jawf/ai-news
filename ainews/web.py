"""FastAPI Web 应用：服务端渲染新闻流 + JSON API + TTL 缓存。"""
import os
from typing import Callable

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ainews import db
from ainews.cache import QueryCache
from ainews.classifier import DEFAULT_RULES

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

    return app
