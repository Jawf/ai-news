# ai-news 重设计 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 ai-news 从「Tkinter + Claude CLI + 飞书推送」改造为「配置驱动多站点抓取 → 规则分类 → SQLite 本地库 → FastAPI 响应式 Web 展示 + 短缓存」，并保留飞书推送作为附加模块。

**Architecture:** 单个 Python 进程承载 FastAPI 主体 + 后台 `schedule` 调度线程。抓取层是配置驱动的源适配器（`sources.yaml` 定义 endpoint/参数/JSONPath 映射），归一化后经规则分类器打类目，去重写入 SQLite。Web 层服务端渲染（Jinja2）+ 进程内 TTL 缓存，监听 `0.0.0.0` 供局域网多设备访问。

**Tech Stack:** Python 3.12+ / uv / FastAPI / uvicorn / Jinja2 / httpx / jsonpath-ng / cachetools / PyYAML / schedule（已有）。测试用 pytest + respx（mock httpx）。

## Global Constraints

- Python 版本：`requires-python = ">=3.12"`（不降低）。
- 依赖管理：uv（`uv add` / `uv run`），不用裸 pip。
- 保留已有 `schedule` 依赖用于调度，不引入 APScheduler。
- 代码标识符（变量/函数/类/文件名）一律英文；面向用户的文案/日志中文。
- 抓取层不写死具体源：所有源经 `sources.yaml` 配置，抓取器通用。
- tushare.pro/news 内部接口形态未确认——不臆造 endpoint；抓取器用录制的样本 fixture 测试，真实 endpoint 在 Task 11 抓包填入。
- Web 服务监听 `0.0.0.0`（局域网可达）。
- 秘钥（飞书 app_secret）迁移到 `.env` / 环境变量，不再明文提交；`.env` 加入 `.gitignore`。
- 去重键 `content_hash` 全局唯一约束在 DB 层强制。
- 新代码放 `ainews/` 包；旧 Tkinter `main.py` 在 Task 10 退役。

---

### Task 1: 依赖与包骨架 + 配置加载

**Files:**
- Modify: `pyproject.toml`
- Create: `ainews/__init__.py`
- Create: `ainews/config.py`
- Create: `sources.yaml`
- Create: `.env.example`
- Modify: `.gitignore`（无则创建）
- Test: `tests/test_config.py`

**Interfaces:**
- Produces:
  - `ainews.config.load_config(path: str | None = None) -> dict`（读 `config.json`，飞书秘钥优先取环境变量 `FEISHU_APP_SECRET` 覆盖）
  - `ainews.config.load_sources(path: str | None = None) -> list[dict]`（读 `sources.yaml`，仅返回 `enabled` 为真的源）

- [ ] **Step 1: 加依赖**

Run:
```bash
uv add fastapi uvicorn jinja2 httpx jsonpath-ng cachetools pyyaml
uv add --dev pytest respx
```
Expected: `pyproject.toml` 的 `dependencies` 新增上述包，`uv.lock` 更新。

- [ ] **Step 2: 写失败测试**

Create `tests/test_config.py`:
```python
import os
import textwrap
from ainews import config


def test_load_sources_filters_disabled(tmp_path):
    p = tmp_path / "sources.yaml"
    p.write_text(textwrap.dedent("""
        - id: xq
          name: 雪球
          enabled: true
          endpoint: "https://example.com/xq"
          method: GET
          mapping: {list_path: "$.items", title: "$.title"}
          poll_interval: 300
        - id: off
          name: 关掉的
          enabled: false
          endpoint: "https://example.com/off"
    """), encoding="utf-8")
    sources = config.load_sources(str(p))
    assert [s["id"] for s in sources] == ["xq"]


def test_load_config_env_overrides_secret(tmp_path, monkeypatch):
    p = tmp_path / "config.json"
    p.write_text('{"feishu_app_secret": "in_file", "feishu_chat_id": "ou_x"}', encoding="utf-8")
    monkeypatch.setenv("FEISHU_APP_SECRET", "from_env")
    cfg = config.load_config(str(p))
    assert cfg["feishu_app_secret"] == "from_env"
    assert cfg["feishu_chat_id"] == "ou_x"
```

- [ ] **Step 3: 运行测试确认失败**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'ainews'`）

- [ ] **Step 4: 写实现**

Create `ainews/__init__.py`:
```python
```
（空文件）

Create `ainews/config.py`:
```python
"""配置加载：config.json（运行参数 + 飞书凭证）与 sources.yaml（源适配）。"""
import json
import os

import yaml

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_config(path: str | None = None) -> dict:
    if path is None:
        path = os.path.join(_BASE, "config.json")
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    # 秘钥优先取环境变量，避免依赖明文文件
    env_secret = os.environ.get("FEISHU_APP_SECRET")
    if env_secret:
        cfg["feishu_app_secret"] = env_secret
    return cfg


def load_sources(path: str | None = None) -> list[dict]:
    if path is None:
        path = os.path.join(_BASE, "sources.yaml")
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or []
    return [s for s in raw if s.get("enabled", True)]
```

Create `sources.yaml`（endpoint 待 Task 11 抓包填入真实值，先给可跑的占位骨架）:
```yaml
- id: xq
  name: 雪球
  enabled: false          # Task 11 抓包确认 endpoint 后置 true
  endpoint: ""
  method: GET
  params: {}
  headers: {}
  mapping:
    list_path: "$.data.items"
    external_id: "$.id"
    time: "$.created_at"
    title: "$.title"
    content: "$.text"
    url: "$.target"
  poll_interval: 300

- id: sina
  name: 新浪财经
  enabled: false
  endpoint: ""
  method: GET
  params: {}
  headers: {}
  mapping:
    list_path: "$.data.items"
    external_id: "$.id"
    time: "$.time"
    title: "$.title"
    content: "$.summary"
    url: "$.url"
  poll_interval: 300
```

Create `.env.example`:
```
FEISHU_APP_SECRET=your_feishu_app_secret_here
```

Create/Modify `.gitignore`（追加）:
```
.env
*.db
__pycache__/
.venv/
```

- [ ] **Step 5: 运行测试确认通过**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS（2 passed）

- [ ] **Step 6: 提交**

```bash
git add pyproject.toml uv.lock ainews/ sources.yaml .env.example .gitignore tests/test_config.py
git commit -m "feat: 包骨架 + 配置加载(config.json/sources.yaml) + 秘钥环境变量化"
```

---

### Task 2: 数据模型 NewsItem

**Files:**
- Create: `ainews/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Produces: `ainews.models.NewsItem`（dataclass，字段 `source/title/content/url/external_id/category/published_at/fetched_at`；属性 `content_hash: str`）

- [ ] **Step 1: 写失败测试**

Create `tests/test_models.py`:
```python
import datetime
from ainews.models import NewsItem


def test_content_hash_uses_external_id_when_present():
    a = NewsItem(source="xq", title="A", external_id="123")
    b = NewsItem(source="xq", title="不同标题", external_id="123")
    assert a.content_hash == b.content_hash  # 同源同 external_id 视为同一条


def test_content_hash_differs_by_source():
    a = NewsItem(source="xq", title="A", external_id="123")
    b = NewsItem(source="sina", title="A", external_id="123")
    assert a.content_hash != b.content_hash


def test_content_hash_falls_back_to_title_time():
    t = datetime.datetime(2026, 7, 23, 8, 0, 0)
    a = NewsItem(source="xq", title="无 id 新闻", published_at=t)
    b = NewsItem(source="xq", title="无 id 新闻", published_at=t)
    assert a.content_hash == b.content_hash
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_models.py -v`
Expected: FAIL（`ModuleNotFoundError` / `ImportError`）

- [ ] **Step 3: 写实现**

Create `ainews/models.py`:
```python
"""统一新闻条目模型。"""
import datetime
import hashlib
from dataclasses import dataclass


@dataclass
class NewsItem:
    source: str
    title: str
    content: str = ""
    url: str = ""
    external_id: str = ""
    category: str = "其他"
    published_at: datetime.datetime | None = None
    fetched_at: datetime.datetime | None = None

    @property
    def content_hash(self) -> str:
        basis = self.external_id or f"{self.title}|{self.published_at}"
        return hashlib.sha256(f"{self.source}|{basis}".encode("utf-8")).hexdigest()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_models.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: 提交**

```bash
git add ainews/models.py tests/test_models.py
git commit -m "feat: NewsItem 模型 + content_hash 去重键"
```

---

### Task 3: SQLite 存储层

**Files:**
- Create: `ainews/db.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Consumes: `ainews.models.NewsItem`
- Produces:
  - `ainews.db.get_conn(db_path: str) -> sqlite3.Connection`
  - `ainews.db.init_db(conn) -> None`
  - `ainews.db.upsert_news(conn, item: NewsItem) -> bool`（新插入返回 True，重复返回 False）
  - `ainews.db.query_news(conn, source=None, category=None, date=None, limit=50, offset=0) -> list[dict]`
  - `ainews.db.record_fetch_run(conn, source, started_at, finished_at, fetched_count, new_count, status, error="") -> None`

- [ ] **Step 1: 写失败测试**

Create `tests/test_db.py`:
```python
import datetime
from ainews import db
from ainews.models import NewsItem


def _conn():
    c = db.get_conn(":memory:")
    db.init_db(c)
    return c


def test_upsert_dedup():
    c = _conn()
    item = NewsItem(source="xq", title="降准", external_id="1",
                    published_at=datetime.datetime(2026, 7, 23, 8, 0))
    assert db.upsert_news(c, item) is True
    assert db.upsert_news(c, item) is False  # 第二次去重
    rows = db.query_news(c)
    assert len(rows) == 1
    assert rows[0]["title"] == "降准"


def test_query_filters_by_source_and_category():
    c = _conn()
    db.upsert_news(c, NewsItem(source="xq", title="A", external_id="1", category="A股"))
    db.upsert_news(c, NewsItem(source="sina", title="B", external_id="2", category="外汇期货"))
    assert len(db.query_news(c, source="xq")) == 1
    assert len(db.query_news(c, category="外汇期货")) == 1
    assert db.query_news(c, category="外汇期货")[0]["source"] == "sina"


def test_record_fetch_run():
    c = _conn()
    now = datetime.datetime(2026, 7, 23, 8, 0)
    db.record_fetch_run(c, "xq", now, now, fetched_count=10, new_count=3, status="ok")
    cur = c.execute("SELECT source, new_count, status FROM fetch_runs")
    row = cur.fetchone()
    assert row[0] == "xq" and row[1] == 3 and row[2] == "ok"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_db.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 写实现**

Create `ainews/db.py`:
```python
"""SQLite 存储：news 表 + fetch_runs 表。"""
import datetime
import sqlite3

from ainews.models import NewsItem


def get_conn(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS news (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            external_id TEXT,
            title TEXT NOT NULL,
            content TEXT DEFAULT '',
            url TEXT DEFAULT '',
            category TEXT DEFAULT '其他',
            published_at TEXT,
            fetched_at TEXT,
            content_hash TEXT NOT NULL UNIQUE
        );
        CREATE INDEX IF NOT EXISTS idx_news_published ON news(published_at);
        CREATE INDEX IF NOT EXISTS idx_news_source ON news(source);
        CREATE INDEX IF NOT EXISTS idx_news_category ON news(category);
        CREATE TABLE IF NOT EXISTS fetch_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            fetched_count INTEGER DEFAULT 0,
            new_count INTEGER DEFAULT 0,
            status TEXT,
            error TEXT DEFAULT ''
        );
        """
    )
    conn.commit()


def _iso(dt: datetime.datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def upsert_news(conn: sqlite3.Connection, item: NewsItem) -> bool:
    fetched = item.fetched_at or datetime.datetime.now()
    try:
        conn.execute(
            """INSERT INTO news
               (source, external_id, title, content, url, category,
                published_at, fetched_at, content_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (item.source, item.external_id, item.title, item.content, item.url,
             item.category, _iso(item.published_at), _iso(fetched), item.content_hash),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False  # content_hash 唯一约束命中 = 重复


def query_news(conn, source=None, category=None, date=None,
               limit=50, offset=0) -> list[dict]:
    clauses, params = [], []
    if source:
        clauses.append("source = ?"); params.append(source)
    if category:
        clauses.append("category = ?"); params.append(category)
    if date:
        clauses.append("substr(published_at, 1, 10) = ?"); params.append(date)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = (f"SELECT * FROM news {where} "
           f"ORDER BY published_at DESC, id DESC LIMIT ? OFFSET ?")
    params.extend([limit, offset])
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def record_fetch_run(conn, source, started_at, finished_at,
                     fetched_count, new_count, status, error="") -> None:
    conn.execute(
        """INSERT INTO fetch_runs
           (source, started_at, finished_at, fetched_count, new_count, status, error)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (source, _iso(started_at), _iso(finished_at),
         fetched_count, new_count, status, error),
    )
    conn.commit()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_db.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: 提交**

```bash
git add ainews/db.py tests/test_db.py
git commit -m "feat: SQLite 存储层(news 去重 + fetch_runs + 筛选查询)"
```

---

### Task 4: 规则关键词分类器

**Files:**
- Create: `ainews/classifier.py`
- Test: `tests/test_classifier.py`

**Interfaces:**
- Produces:
  - `ainews.classifier.DEFAULT_RULES: dict[str, list[str]]`
  - `ainews.classifier.classify(title: str, content: str = "", rules: dict | None = None) -> str`（返回类目名；无命中返回 "其他"）

- [ ] **Step 1: 写失败测试**

Create `tests/test_classifier.py`:
```python
from ainews.classifier import classify


def test_classify_macro():
    assert classify("央行宣布降准0.5个百分点") == "宏观政策"


def test_classify_a_share():
    assert classify("A股三大指数集体上涨，沪指涨1.2%") == "A股"


def test_classify_forex():
    assert classify("在岸人民币兑美元汇率大幅波动") == "外汇期货"


def test_classify_default_other():
    assert classify("某公司发布不相关的公告内容") in ("公司个股", "其他")


def test_custom_rules_override():
    rules = {"自定义类": ["特定词"]}
    assert classify("含特定词的标题", rules=rules) == "自定义类"
    assert classify("不含关键词", rules=rules) == "其他"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_classifier.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 写实现**

Create `ainews/classifier.py`:
```python
"""规则关键词分类：标题+正文命中关键词即归类，可传入自定义 rules 覆盖。"""

DEFAULT_RULES: dict[str, list[str]] = {
    "宏观政策": ["央行", "降准", "降息", "国务院", "财政部", "货币政策", "GDP", "CPI", "政策"],
    "A股": ["A股", "沪指", "深成指", "创业板", "上证", "科创板", "北向资金"],
    "港美股": ["港股", "恒生", "美股", "纳斯达克", "道琼斯", "标普", "美联储"],
    "外汇期货": ["人民币", "汇率", "外汇", "原油", "黄金", "期货", "美元"],
    "公司个股": ["公司", "财报", "业绩", "股份", "回购", "增持", "减持", "上市"],
}


def classify(title: str, content: str = "", rules: dict | None = None) -> str:
    rules = rules if rules is not None else DEFAULT_RULES
    text = f"{title} {content}"
    for category, keywords in rules.items():
        if any(kw in text for kw in keywords):
            return category
    return "其他"
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_classifier.py -v`
Expected: PASS（5 passed）

- [ ] **Step 5: 提交**

```bash
git add ainews/classifier.py tests/test_classifier.py
git commit -m "feat: 规则关键词分类器"
```

---

### Task 5: 配置驱动的源适配器（抓取 + 归一化）

**Files:**
- Create: `ainews/fetcher.py`
- Test: `tests/test_fetcher.py`

**Interfaces:**
- Consumes: `ainews.models.NewsItem`, `ainews.classifier.classify`
- Produces:
  - `ainews.fetcher.normalize(raw: dict, source_cfg: dict) -> list[NewsItem]`（按 mapping 的 JSONPath 提取并分类）
  - `ainews.fetcher.fetch_source(source_cfg: dict, client: httpx.Client | None = None) -> list[NewsItem]`

- [ ] **Step 1: 写失败测试**

Create `tests/test_fetcher.py`:
```python
import httpx
import respx
from ainews import fetcher


SOURCE = {
    "id": "xq", "name": "雪球",
    "endpoint": "https://example.com/news",
    "method": "GET", "params": {}, "headers": {},
    "mapping": {
        "list_path": "$.data.items",
        "external_id": "$.id",
        "time": "$.created_at",
        "title": "$.title",
        "content": "$.text",
        "url": "$.target",
    },
}

SAMPLE = {"data": {"items": [
    {"id": "1", "created_at": "2026-07-23T08:00:00", "title": "央行降准",
     "text": "释放流动性", "target": "https://x.com/1"},
    {"id": "2", "created_at": "2026-07-23T08:05:00", "title": "无关公告",
     "text": "普通内容", "target": "https://x.com/2"},
]}}


def test_normalize_maps_fields_and_classifies():
    items = fetcher.normalize(SAMPLE, SOURCE)
    assert len(items) == 2
    assert items[0].source == "xq"
    assert items[0].title == "央行降准"
    assert items[0].external_id == "1"
    assert items[0].url == "https://x.com/1"
    assert items[0].category == "宏观政策"


@respx.mock
def test_fetch_source_http():
    respx.get("https://example.com/news").mock(
        return_value=httpx.Response(200, json=SAMPLE))
    items = fetcher.fetch_source(SOURCE)
    assert len(items) == 2
    assert items[1].title == "无关公告"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_fetcher.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 写实现**

Create `ainews/fetcher.py`:
```python
"""配置驱动源适配器：按 source_cfg 抓取 + JSONPath 映射为 NewsItem。"""
import datetime

import httpx
from jsonpath_ng import parse as jp_parse

from ainews.classifier import classify
from ainews.models import NewsItem

_cache: dict[str, object] = {}


def _compile(path: str):
    if path not in _cache:
        _cache[path] = jp_parse(path)
    return _cache[path]


def _first(obj, path: str, default=""):
    if not path:
        return default
    matches = _compile(path).find(obj)
    return matches[0].value if matches else default


def _parse_time(raw) -> datetime.datetime | None:
    if not raw:
        return None
    if isinstance(raw, (int, float)):  # 毫秒/秒级时间戳
        ts = raw / 1000 if raw > 1e12 else raw
        return datetime.datetime.fromtimestamp(ts)
    try:
        return datetime.datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None


def normalize(raw: dict, source_cfg: dict) -> list[NewsItem]:
    mapping = source_cfg["mapping"]
    rows = _first(raw, mapping.get("list_path", "$"), default=[])
    if not isinstance(rows, list):
        rows = [rows]
    items: list[NewsItem] = []
    now = datetime.datetime.now()
    for row in rows:
        title = str(_first(row, mapping.get("title", ""))).strip()
        if not title:
            continue
        content = str(_first(row, mapping.get("content", "")))
        item = NewsItem(
            source=source_cfg["id"],
            title=title,
            content=content,
            url=str(_first(row, mapping.get("url", ""))),
            external_id=str(_first(row, mapping.get("external_id", ""))),
            published_at=_parse_time(_first(row, mapping.get("time", ""), default=None)),
            fetched_at=now,
        )
        item.category = classify(item.title, item.content)
        items.append(item)
    return items


def fetch_source(source_cfg: dict, client: httpx.Client | None = None) -> list[NewsItem]:
    owns = client is None
    client = client or httpx.Client(timeout=15)
    try:
        resp = client.request(
            source_cfg.get("method", "GET").upper(),
            source_cfg["endpoint"],
            params=source_cfg.get("params") or None,
            headers=source_cfg.get("headers") or None,
        )
        resp.raise_for_status()
        return normalize(resp.json(), source_cfg)
    finally:
        if owns:
            client.close()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_fetcher.py -v`
Expected: PASS（2 passed）

- [ ] **Step 5: 提交**

```bash
git add ainews/fetcher.py tests/test_fetcher.py
git commit -m "feat: 配置驱动源适配器(JSONPath 映射 + 归一化 + 分类)"
```

---

### Task 6: TTL 短缓存

**Files:**
- Create: `ainews/cache.py`
- Test: `tests/test_cache.py`

**Interfaces:**
- Produces: `ainews.cache.QueryCache(ttl: float, maxsize: int = 128)`，方法 `get_or_set(key: str, producer: callable) -> object`

- [ ] **Step 1: 写失败测试**

Create `tests/test_cache.py`:
```python
from ainews.cache import QueryCache


def test_cache_hits_within_ttl():
    calls = {"n": 0}
    def producer():
        calls["n"] += 1
        return calls["n"]
    cache = QueryCache(ttl=100)
    assert cache.get_or_set("k", producer) == 1
    assert cache.get_or_set("k", producer) == 1  # 命中缓存，producer 不再调用
    assert calls["n"] == 1


def test_cache_distinct_keys():
    cache = QueryCache(ttl=100)
    assert cache.get_or_set("a", lambda: "A") == "A"
    assert cache.get_or_set("b", lambda: "B") == "B"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_cache.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 写实现**

Create `ainews/cache.py`:
```python
"""进程内 TTL 缓存，按筛选参数组合缓存查询结果。"""
from typing import Callable

from cachetools import TTLCache


class QueryCache:
    def __init__(self, ttl: float, maxsize: int = 128):
        self._store: TTLCache = TTLCache(maxsize=maxsize, ttl=ttl)

    def get_or_set(self, key: str, producer: Callable[[], object]) -> object:
        if key in self._store:
            return self._store[key]
        value = producer()
        self._store[key] = value
        return value
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_cache.py -v`
Expected: PASS（2 passed）

- [ ] **Step 5: 提交**

```bash
git add ainews/cache.py tests/test_cache.py
git commit -m "feat: TTL 短缓存"
```

---

### Task 7: FastAPI Web 应用 + 响应式模板

**Files:**
- Create: `ainews/web.py`
- Create: `ainews/templates/base.html`
- Create: `ainews/templates/index.html`
- Create: `ainews/static/style.css`
- Test: `tests/test_web.py`

**Interfaces:**
- Consumes: `ainews.db.query_news`, `ainews.cache.QueryCache`
- Produces: `ainews.web.create_app(conn_factory: callable, cache: QueryCache, categories: list[str] | None = None) -> FastAPI`
  - 路由 `GET /`（HTML，query 参数 `source/category/date/page`）
  - 路由 `GET /api/news`（JSON，同参数，返回 `{"items": [...], "page": n}`）

- [ ] **Step 1: 写失败测试**

Create `tests/test_web.py`:
```python
from fastapi.testclient import TestClient
from ainews import db, web
from ainews.cache import QueryCache
from ainews.models import NewsItem


def _app():
    conn = db.get_conn(":memory:")
    db.init_db(conn)
    db.upsert_news(conn, NewsItem(source="xq", title="央行降准", external_id="1", category="宏观政策"))
    db.upsert_news(conn, NewsItem(source="sina", title="A股上涨", external_id="2", category="A股"))
    return web.create_app(lambda: conn, QueryCache(ttl=30))


def test_index_html_lists_news():
    client = TestClient(_app())
    r = client.get("/")
    assert r.status_code == 200
    assert "央行降准" in r.text
    assert "A股上涨" in r.text


def test_api_news_json_filter():
    client = TestClient(_app())
    r = client.get("/api/news", params={"source": "xq"})
    assert r.status_code == 200
    data = r.json()
    assert len(data["items"]) == 1
    assert data["items"][0]["title"] == "央行降准"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_web.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 写实现**

Create `ainews/web.py`:
```python
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
        return templates.TemplateResponse("index.html", {
            "request": request, "items": items, "categories": cats,
            "source": source, "category": category, "date": date, "page": page,
        })

    @app.get("/api/news")
    def api_news(source: str = "", category: str = "", date: str = "", page: int = 1):
        items = _query(source or None, category or None, date or None, page)
        return JSONResponse({"items": items, "page": page})

    return app
```

Create `ainews/templates/base.html`:
```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>财经新闻</title>
  <link rel="stylesheet" href="/static/style.css">
</head>
<body>
  <header class="topbar"><h1>📰 财经新闻</h1></header>
  <main>{% block content %}{% endblock %}</main>
</body>
</html>
```

Create `ainews/templates/index.html`:
```html
{% extends "base.html" %}
{% block content %}
<form class="filters" method="get" action="/">
  <select name="category" onchange="this.form.submit()">
    <option value="">全部类目</option>
    {% for c in categories %}
    <option value="{{ c }}" {% if c == category %}selected{% endif %}>{{ c }}</option>
    {% endfor %}
  </select>
  <input type="date" name="date" value="{{ date }}" onchange="this.form.submit()">
</form>
<ul class="news-list">
  {% for it in items %}
  <li class="news-card">
    <div class="meta"><span class="src">{{ it.source }}</span>
      <span class="cat">{{ it.category }}</span>
      <span class="time">{{ it.published_at or '' }}</span></div>
    <a class="title" href="{{ it.url }}" target="_blank" rel="noopener">{{ it.title }}</a>
    {% if it.content %}<p class="content">{{ it.content }}</p>{% endif %}
  </li>
  {% else %}
  <li class="empty">暂无数据</li>
  {% endfor %}
</ul>
<nav class="pager">
  {% if page > 1 %}<a href="?category={{ category }}&date={{ date }}&page={{ page - 1 }}">上一页</a>{% endif %}
  <span>第 {{ page }} 页</span>
  {% if items|length == 30 %}<a href="?category={{ category }}&date={{ date }}&page={{ page + 1 }}">下一页</a>{% endif %}
</nav>
{% endblock %}
```

Create `ainews/static/style.css`（mobile-first + iPad/PC 断点）:
```css
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
  background: #f5f6f8; color: #1a1a1a; line-height: 1.5; }
.topbar { background: #b91c1c; color: #fff; padding: 14px 16px; position: sticky; top: 0; }
.topbar h1 { font-size: 18px; }
main { max-width: 1200px; margin: 0 auto; padding: 12px; }
.filters { display: flex; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }
.filters select, .filters input { padding: 8px; border: 1px solid #ddd; border-radius: 8px; font-size: 14px; }
.news-list { list-style: none; display: grid; grid-template-columns: 1fr; gap: 10px; }
.news-card { background: #fff; border-radius: 12px; padding: 14px; box-shadow: 0 1px 3px rgba(0,0,0,.06); }
.news-card .meta { font-size: 12px; color: #888; display: flex; gap: 10px; margin-bottom: 6px; }
.news-card .cat { color: #b91c1c; }
.news-card .title { font-size: 16px; font-weight: 600; color: #111; text-decoration: none; display: block; }
.news-card .content { font-size: 14px; color: #444; margin-top: 6px; }
.empty { text-align: center; color: #999; padding: 40px; }
.pager { display: flex; justify-content: center; gap: 16px; align-items: center; padding: 20px; }
.pager a { color: #b91c1c; text-decoration: none; }
/* iPad 双列 */
@media (min-width: 768px) { .news-list { grid-template-columns: 1fr 1fr; } }
/* PC 多列 */
@media (min-width: 1100px) { .news-list { grid-template-columns: 1fr 1fr 1fr; } }
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_web.py -v`
Expected: PASS（2 passed）

- [ ] **Step 5: 提交**

```bash
git add ainews/web.py ainews/templates/ ainews/static/ tests/test_web.py
git commit -m "feat: FastAPI 响应式 Web(SSR 新闻流 + JSON API + 缓存)"
```

---

### Task 8: 抓取编排 + 调度器

**Files:**
- Create: `ainews/pipeline.py`
- Create: `ainews/scheduler.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `ainews.fetcher.fetch_source`, `ainews.db.*`
- Produces:
  - `ainews.pipeline.run_source(conn, source_cfg, fetch=fetcher.fetch_source) -> dict`（抓一个源→入库→记 fetch_run，返回 `{"fetched": n, "new": m, "status": str}`；失败隔离不抛）
  - `ainews.pipeline.run_all(conn, sources) -> list[dict]`
  - `ainews.scheduler.start_scheduler(conn_factory, sources, stop_event=None) -> None`（阻塞循环，按源 poll_interval 调度）

- [ ] **Step 1: 写失败测试**

Create `tests/test_pipeline.py`:
```python
from ainews import db, pipeline
from ainews.models import NewsItem


SRC = {"id": "xq", "name": "雪球", "endpoint": "x", "mapping": {}}


def test_run_source_inserts_and_counts():
    conn = db.get_conn(":memory:"); db.init_db(conn)
    def fake_fetch(cfg, client=None):
        return [NewsItem(source="xq", title="降准", external_id="1"),
                NewsItem(source="xq", title="上涨", external_id="2")]
    res = pipeline.run_source(conn, SRC, fetch=fake_fetch)
    assert res["fetched"] == 2 and res["new"] == 2 and res["status"] == "ok"
    # 再跑一次全部重复
    res2 = pipeline.run_source(conn, SRC, fetch=fake_fetch)
    assert res2["new"] == 0


def test_run_source_isolates_failure():
    conn = db.get_conn(":memory:"); db.init_db(conn)
    def boom(cfg, client=None):
        raise RuntimeError("network down")
    res = pipeline.run_source(conn, SRC, fetch=boom)
    assert res["status"] == "error"
    assert res["new"] == 0  # 不抛异常，记录错误
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_pipeline.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 写实现**

Create `ainews/pipeline.py`:
```python
"""抓取编排：单源抓取→入库→记录运行；失败隔离。"""
import datetime
import logging

from ainews import db, fetcher

logger = logging.getLogger(__name__)


def run_source(conn, source_cfg: dict, fetch=fetcher.fetch_source) -> dict:
    started = datetime.datetime.now()
    source_id = source_cfg.get("id", "?")
    try:
        items = fetch(source_cfg)
        new = sum(1 for it in items if db.upsert_news(conn, it))
        finished = datetime.datetime.now()
        db.record_fetch_run(conn, source_id, started, finished,
                            fetched_count=len(items), new_count=new, status="ok")
        logger.info("源 %s 抓取 %d 条，新增 %d 条", source_id, len(items), new)
        return {"fetched": len(items), "new": new, "status": "ok"}
    except Exception as e:  # 失败隔离：一个源挂掉不影响其他
        finished = datetime.datetime.now()
        db.record_fetch_run(conn, source_id, started, finished,
                            fetched_count=0, new_count=0, status="error", error=str(e))
        logger.warning("源 %s 抓取失败: %s", source_id, e)
        return {"fetched": 0, "new": 0, "status": "error"}


def run_all(conn, sources: list[dict]) -> list[dict]:
    return [run_source(conn, s) for s in sources]
```

Create `ainews/scheduler.py`:
```python
"""后台调度：按每源 poll_interval 周期性抓取。"""
import logging
import time

import schedule

from ainews import pipeline

logger = logging.getLogger(__name__)


def start_scheduler(conn_factory, sources: list[dict], stop_event=None) -> None:
    for s in sources:
        interval = int(s.get("poll_interval", 300))
        schedule.every(interval).seconds.do(
            lambda cfg=s: pipeline.run_source(conn_factory(), cfg))
    # 启动即先跑一轮
    pipeline.run_all(conn_factory(), sources)
    logger.info("调度器启动，%d 个源", len(sources))
    while stop_event is None or not stop_event.is_set():
        schedule.run_pending()
        time.sleep(1)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_pipeline.py -v`
Expected: PASS（2 passed）

- [ ] **Step 5: 提交**

```bash
git add ainews/pipeline.py ainews/scheduler.py tests/test_pipeline.py
git commit -m "feat: 抓取编排(失败隔离) + schedule 调度器"
```

---

### Task 9: 飞书推送模块（附加）

**Files:**
- Create: `ainews/push.py`
- Modify: `job_runner.py`（仅保留可复用的飞书函数被 import；不改动其逻辑）
- Test: `tests/test_push.py`

**Interfaces:**
- Consumes: `ainews.db.query_news`, `job_runner.send_news`
- Produces:
  - `ainews.push.select_top_n(conn, n: int = 10, date: str | None = None) -> list[dict]`
  - `ainews.push.format_digest(items: list[dict], date: str) -> str`
  - `ainews.push.run_push(config: dict, conn, n: int = 10, sender=None) -> bool`

- [ ] **Step 1: 写失败测试**

Create `tests/test_push.py`:
```python
from ainews import db, push
from ainews.models import NewsItem


def test_format_digest_numbers_items():
    items = [{"source": "xq", "title": "降准", "content": "释放流动性"},
             {"source": "sina", "title": "上涨", "content": ""}]
    text = push.format_digest(items, "2026年07月23日")
    assert "财经TOP" in text
    assert "1." in text and "2." in text
    assert "降准" in text


def test_run_push_calls_sender_with_digest():
    conn = db.get_conn(":memory:"); db.init_db(conn)
    db.upsert_news(conn, NewsItem(source="xq", title="降准", external_id="1"))
    captured = {}
    def sender(config, content, log):
        captured["content"] = content
        return True
    ok = push.run_push({"feishu_chat_id": "ou_x"}, conn, n=10, sender=sender)
    assert ok is True
    assert "降准" in captured["content"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_push.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 写实现**

Create `ainews/push.py`:
```python
"""飞书推送（附加）：从库里选 Top-N，格式化后复用 job_runner 的发送逻辑。"""
import datetime
import logging

from ainews import db

logger = logging.getLogger(__name__)


def select_top_n(conn, n: int = 10, date: str | None = None) -> list[dict]:
    if date is None:
        date = datetime.date.today().strftime("%Y-%m-%d")
    rows = db.query_news(conn, date=date, limit=n, offset=0)
    if not rows:  # 当天无数据则退回最近 N 条
        rows = db.query_news(conn, limit=n, offset=0)
    return rows


def format_digest(items: list[dict], date: str) -> str:
    lines = [f"📰 {date} 财经TOP{len(items)}", ""]
    for i, it in enumerate(items, 1):
        lines.append(f"{i}. 【{it['source']}】{it['title']}")
        if it.get("content"):
            lines.append(f"   摘要：{it['content'][:50]}")
        lines.append("")
    return "\n".join(lines).strip()


def run_push(config: dict, conn, n: int = 10, sender=None) -> bool:
    if sender is None:
        from job_runner import send_news as sender  # 复用既有发送(nanobot + 飞书 API 兜底)
    date_cn = datetime.date.today().strftime("%Y年%m月%d日")
    items = select_top_n(conn, n=n)
    if not items:
        logger.warning("无新闻可推送")
        return False
    content = format_digest(items, date_cn)
    return sender(config, content, lambda m: logger.info(m))
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_push.py -v`
Expected: PASS（2 passed）

- [ ] **Step 5: 提交**

```bash
git add ainews/push.py tests/test_push.py
git commit -m "feat: 飞书推送模块(Top-N 选取 + digest + 复用既有发送)"
```

---

### Task 10: CLI 入口 + 退役 Tkinter GUI

**Files:**
- Create: `ainews/cli.py`
- Create: `ainews/app.py`（组装 conn/cache/scheduler 线程 + FastAPI）
- Modify: `run_once.py`（改为调用 `ainews.pipeline.run_all` + 可选推送）
- Delete: `main.py`（Tkinter GUI 退役）
- Modify: `README.md`（更新用法段）
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: 前述所有模块
- Produces:
  - `ainews.app.build_app(config, sources) -> (FastAPI, conn)`（供 uvicorn 加载）
  - `ainews.cli.main(argv: list[str] | None = None) -> int`，子命令：`serve` / `fetch-once` / `push`

- [ ] **Step 1: 写失败测试**

Create `tests/test_cli.py`:
```python
from ainews import cli


def test_fetch_once_runs_pipeline(monkeypatch, tmp_path):
    called = {}
    monkeypatch.setattr(cli, "_load_sources", lambda: [{"id": "xq", "endpoint": "x", "mapping": {}}])
    monkeypatch.setattr(cli, "_open_conn", lambda: __import__("ainews.db", fromlist=["x"]).get_conn(":memory:"))
    def fake_run_all(conn, sources):
        called["n"] = len(sources); return [{"fetched": 0, "new": 0, "status": "ok"}]
    monkeypatch.setattr("ainews.pipeline.run_all", fake_run_all)
    monkeypatch.setattr("ainews.db.init_db", lambda c: None)
    rc = cli.main(["fetch-once"])
    assert rc == 0 and called["n"] == 1
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_cli.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 写实现**

Create `ainews/app.py`:
```python
"""组装应用：DB + 缓存 + 后台调度线程 + FastAPI。"""
import os
import threading

from ainews import config as cfg_mod
from ainews import db, scheduler, web
from ainews.cache import QueryCache

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(_BASE, "news.db")


def build_app(config: dict, sources: list[dict]):
    db.init_db(db.get_conn(DB_PATH))  # 确保表存在

    def conn_factory():
        return db.get_conn(DB_PATH)

    cache = QueryCache(ttl=float(config.get("cache_ttl", 45)))
    app = web.create_app(conn_factory, cache)

    if config.get("scheduler_enabled", True) and sources:
        t = threading.Thread(
            target=scheduler.start_scheduler,
            args=(conn_factory, sources), daemon=True)
        t.start()
    return app, conn_factory
```

Create `ainews/cli.py`:
```python
"""命令行入口：serve / fetch-once / push。"""
import argparse
import logging
import sys

import uvicorn

from ainews import app as app_mod
from ainews import config as cfg_mod
from ainews import db, pipeline, push

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")


def _load_config():
    return cfg_mod.load_config()


def _load_sources():
    return cfg_mod.load_sources()


def _open_conn():
    return db.get_conn(app_mod.DB_PATH)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ainews")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_serve = sub.add_parser("serve", help="启动 Web 服务 + 调度")
    p_serve.add_argument("--host", default="0.0.0.0")
    p_serve.add_argument("--port", type=int, default=8000)
    sub.add_parser("fetch-once", help="抓取一轮后退出")
    p_push = sub.add_parser("push", help="选 Top-N 推送飞书")
    p_push.add_argument("-n", type=int, default=10)
    args = parser.parse_args(argv)

    if args.cmd == "serve":
        config, sources = _load_config(), _load_sources()
        application, _ = app_mod.build_app(config, sources)
        uvicorn.run(application, host=args.host, port=args.port)
        return 0

    if args.cmd == "fetch-once":
        conn = _open_conn()
        db.init_db(conn)
        results = pipeline.run_all(conn, _load_sources())
        print(f"抓取完成：{results}")
        return 0

    if args.cmd == "push":
        conn = _open_conn()
        db.init_db(conn)
        ok = push.run_push(_load_config(), conn, n=args.n)
        return 0 if ok else 1

    return 2


if __name__ == "__main__":
    sys.exit(main())
```

Replace `run_once.py` 内容:
```python
"""run_once.py - 无 GUI 单次抓取入口（配 Windows 任务计划用）。

Usage: uv run python run_once.py
"""
import sys

from ainews.cli import main

if __name__ == "__main__":
    sys.exit(main(["fetch-once"]))
```

Delete `main.py`:
```bash
git rm main.py
```

Modify `README.md`：把「GUI 界面说明」「任务执行流程」段替换为新用法（`uv run python -m ainews.cli serve` 启动 Web、`fetch-once` 抓取、`push` 推送；说明局域网访问 `http://<本机IP>:8000`）。保留飞书格式示例与常见问题段，删除 Tkinter 相关描述。

- [ ] **Step 4: 运行测试确认通过 + 端到端手测**

Run: `uv run pytest tests/test_cli.py -v`
Expected: PASS（1 passed）

Run（端到端，无真实源时应正常空跑）: `uv run python -m ainews.cli serve --port 8000`
Expected: uvicorn 启动，浏览器访问 `http://127.0.0.1:8000/` 显示"暂无数据"页面（无报错）。Ctrl+C 退出。

- [ ] **Step 5: 提交**

```bash
git add ainews/app.py ainews/cli.py run_once.py README.md
git rm main.py
git commit -m "feat: CLI 入口(serve/fetch-once/push) + 退役 Tkinter GUI + 更新 README"
```

---

### Task 11: tushare 源接口抓包 + 启用真实源

**Files:**
- Modify: `sources.yaml`（填入 xq / sina 的真实 endpoint / params / headers / mapping，置 `enabled: true`）
- Create: `tests/fixtures/tushare_xq_sample.json`（抓包录制的真实响应样本，供回归）
- Create: `tests/test_fetcher_tushare.py`（用真实样本验证 mapping）

**Interfaces:**
- Consumes: `ainews.fetcher.normalize`
- 无新增对外接口。

> **抓包方法（二选一）**：
> ① 用 claude-in-chrome 打开 `https://tushare.pro/news/xq` 与 `/news/sina`，在 Network 面板捕获加载新闻列表的 XHR/fetch 请求，记录 URL、method、query/body 参数、必要 cookie/token、响应 JSON。
> ② 由 Human 在浏览器 devtools 里复制该请求（Copy as cURL）贴给实现者。
> 若确认该接口需登录态且无法稳定复现，按设计文档「回退方案」改抓源站或官方 API——只改 `sources.yaml` 该源配置，其余代码不动。

- [ ] **Step 1: 抓包获取真实接口**

用上述方法捕获 xq / sina 列表接口。把一份真实响应存为 `tests/fixtures/tushare_xq_sample.json`。

- [ ] **Step 2: 写基于真实样本的回归测试**

Create `tests/test_fetcher_tushare.py`（`MAPPING` 按抓包实际结构填写）:
```python
import json
import os
from ainews import fetcher

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "tushare_xq_sample.json")


def test_xq_sample_maps_nonempty():
    with open(FIX, encoding="utf-8") as f:
        raw = json.load(f)
    source = {  # 与 sources.yaml 的 xq 配置保持一致
        "id": "xq", "name": "雪球",
        "mapping": {
            "list_path": "$.<按样本填>",
            "title": "$.<按样本填>",
            "content": "$.<按样本填>",
            "url": "$.<按样本填>",
            "external_id": "$.<按样本填>",
            "time": "$.<按样本填>",
        },
    }
    items = fetcher.normalize(raw, source)
    assert len(items) > 0
    assert all(it.title for it in items)
```

- [ ] **Step 3: 运行测试确认失败/调整 mapping**

Run: `uv run pytest tests/test_fetcher_tushare.py -v`
Expected: 初次可能 FAIL（JSONPath 未对准）→ 按样本调整 `mapping` 直到 PASS。

- [ ] **Step 4: 更新 sources.yaml 并端到端验证**

把 `sources.yaml` 的 xq / sina 填真实值并 `enabled: true`，然后:

Run: `uv run python -m ainews.cli fetch-once`
Expected: 打印各源抓取条数，`news.db` 有真实数据。

Run: `uv run python -m ainews.cli serve` → 浏览器访问首页
Expected: 看到真实新闻卡片，可按类目/日期筛选；手机/iPad/PC 宽度下布局分别为单/双/三列。

- [ ] **Step 5: 提交**

```bash
git add sources.yaml tests/fixtures/ tests/test_fetcher_tushare.py
git commit -m "feat: 抓包确认 tushare xq/sina 接口并启用真实源 + 样本回归"
```

---

## Phase 2：分析洞察层

### Task 12: 分析/自选股存储扩展

**Files:**
- Modify: `ainews/db.py`
- Test: `tests/test_db_analysis.py`

**Interfaces:**
- Produces:
  - `ainews.db.save_analysis_run(conn, run_at: datetime, status: str, payload: dict | None = None, error: str = "") -> None`
  - `ainews.db.latest_analysis(conn) -> dict | None`（最近一次 `status='ok'` 的 payload dict；无则 None）
  - `ainews.db.add_watch(conn, code: str, name: str, aliases: list[str] | None = None) -> bool`（重复 code 返回 False）
  - `ainews.db.remove_watch(conn, code: str) -> bool`
  - `ainews.db.list_watch(conn) -> list[dict]`（含 `code/name/aliases`，aliases 已反序列化为 list）

- [ ] **Step 1: 写失败测试**

Create `tests/test_db_analysis.py`:
```python
import datetime
from ainews import db


def _conn():
    c = db.get_conn(":memory:")
    db.init_db(c)
    return c


def test_save_and_latest_analysis():
    c = _conn()
    t = datetime.datetime(2026, 7, 23, 8, 0)
    db.save_analysis_run(c, t, "error", payload=None, error="boom")
    db.save_analysis_run(c, t, "ok", payload={"top20": [{"title": "降准"}]})
    latest = db.latest_analysis(c)
    assert latest["top20"][0]["title"] == "降准"


def test_latest_analysis_none_when_empty():
    assert db.latest_analysis(_conn()) is None


def test_watchlist_crud():
    c = _conn()
    assert db.add_watch(c, "688981", "中芯国际", aliases=["中芯"]) is True
    assert db.add_watch(c, "688981", "中芯国际") is False  # 重复 code
    rows = db.list_watch(c)
    assert rows[0]["name"] == "中芯国际"
    assert rows[0]["aliases"] == ["中芯"]
    assert db.remove_watch(c, "688981") is True
    assert db.list_watch(c) == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_db_analysis.py -v`
Expected: FAIL（`AttributeError: module 'ainews.db' has no attribute 'save_analysis_run'`）

- [ ] **Step 3: 写实现**

Modify `ainews/db.py` —— `init_db` 的 `executescript` 末尾追加两张表：
```sql
        CREATE TABLE IF NOT EXISTS analysis_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_at TEXT,
            status TEXT,
            error TEXT DEFAULT '',
            payload_json TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS watchlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            aliases_json TEXT DEFAULT '[]',
            added_at TEXT
        );
```

文件末尾追加（并在文件头 `import json`）：
```python
def save_analysis_run(conn, run_at, status, payload=None, error="") -> None:
    conn.execute(
        "INSERT INTO analysis_runs (run_at, status, error, payload_json) VALUES (?, ?, ?, ?)",
        (_iso(run_at), status, error, json.dumps(payload or {}, ensure_ascii=False)),
    )
    conn.commit()


def latest_analysis(conn) -> dict | None:
    row = conn.execute(
        "SELECT payload_json FROM analysis_runs WHERE status='ok' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return json.loads(row[0]) if row else None


def add_watch(conn, code: str, name: str, aliases: list[str] | None = None) -> bool:
    import datetime as _dt
    try:
        conn.execute(
            "INSERT INTO watchlist (code, name, aliases_json, added_at) VALUES (?, ?, ?, ?)",
            (code, name, json.dumps(aliases or [], ensure_ascii=False),
             _dt.datetime.now().isoformat()),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def remove_watch(conn, code: str) -> bool:
    cur = conn.execute("DELETE FROM watchlist WHERE code = ?", (code,))
    conn.commit()
    return cur.rowcount > 0


def list_watch(conn) -> list[dict]:
    rows = conn.execute("SELECT code, name, aliases_json FROM watchlist ORDER BY id").fetchall()
    return [{"code": r["code"], "name": r["name"], "aliases": json.loads(r["aliases_json"])}
            for r in rows]
```

- [ ] **Step 4: 运行测试确认通过（含全量回归）**

Run: `uv run pytest -v`
Expected: 全部 PASS（Phase 1 既有测试不受影响）

- [ ] **Step 5: 提交**

```bash
git add ainews/db.py tests/test_db_analysis.py
git commit -m "feat: analysis_runs + watchlist 存储"
```

---

### Task 13: Claude 批量分析引擎

**Files:**
- Create: `ainews/analyzer.py`
- Test: `tests/test_analyzer.py`

**Interfaces:**
- Consumes: `ainews.db.query_news / save_analysis_run`
- Produces:
  - `ainews.analyzer.build_analysis_prompt(items: list[dict], date_cn: str) -> str`
  - `ainews.analyzer.parse_analysis_output(text: str) -> dict`（从 CLI 输出中提取首个 JSON 对象；无法解析抛 `ValueError`）
  - `ainews.analyzer.run_analysis(config: dict, conn, runner=None) -> bool`（runner(prompt, config)->str，默认走 `claude --print` 子进程；成功落 ok 快照，失败落 error 记录并返回 False）

- [ ] **Step 1: 写失败测试**

Create `tests/test_analyzer.py`:
```python
import json
import pytest
from ainews import analyzer, db
from ainews.models import NewsItem

PAYLOAD = {
    "top20": [{"title": "央行降准", "source": "xq", "importance": 95,
               "sentiment": "利好", "sectors": ["银行"],
               "stocks": [{"name": "招商银行", "code": "600036"}],
               "reason": "流动性宽松"}],
    "bullish": {"directions": ["宽松"], "sectors": ["银行"],
                "stocks": [{"name": "招商银行", "code": "600036"}]},
    "bearish": {"directions": [], "sectors": [], "stocks": []},
    "company_sina": [{"company": "某公司", "sentiment": "利空", "summary": "业绩预亏"}],
    "top5_bullish": [{"title": "央行降准", "reason": "全面利好"}],
}


def test_build_prompt_contains_news_and_contract():
    p = analyzer.build_analysis_prompt([{"title": "降准", "source": "xq", "content": "x"}], "2026年07月23日")
    assert "降准" in p and "top20" in p and "company_sina" in p


def test_parse_extracts_json_from_noise():
    text = "以下是分析结果：\n" + json.dumps(PAYLOAD, ensure_ascii=False) + "\n完毕"
    out = analyzer.parse_analysis_output(text)
    assert out["top20"][0]["sentiment"] == "利好"


def test_parse_raises_on_garbage():
    with pytest.raises(ValueError):
        analyzer.parse_analysis_output("没有任何 JSON")


def test_run_analysis_saves_snapshot():
    conn = db.get_conn(":memory:"); db.init_db(conn)
    db.upsert_news(conn, NewsItem(source="xq", title="央行降准", external_id="1"))
    ok = analyzer.run_analysis({}, conn,
                               runner=lambda prompt, cfg: json.dumps(PAYLOAD, ensure_ascii=False))
    assert ok is True
    assert db.latest_analysis(conn)["top5_bullish"][0]["title"] == "央行降准"


def test_run_analysis_records_failure():
    conn = db.get_conn(":memory:"); db.init_db(conn)
    def bad_runner(prompt, cfg):
        raise RuntimeError("cli down")
    assert analyzer.run_analysis({}, conn, runner=bad_runner) is False
    row = conn.execute("SELECT status FROM analysis_runs ORDER BY id DESC LIMIT 1").fetchone()
    assert row[0] == "error"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_analyzer.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 写实现**

Create `ainews/analyzer.py`:
```python
"""Claude 批量分析：当日新闻 → Top20/利好利空/公司归类/Top5 洞察快照。"""
import datetime
import json
import logging
import re
import subprocess

from ainews import db

logger = logging.getLogger(__name__)

_CONTRACT = """{
  "top20": [{"title": "...", "source": "...", "importance": 0-100,
             "sentiment": "利好|利空|中性", "sectors": ["..."],
             "stocks": [{"name": "...", "code": "..."}], "reason": "一句影响判断"}],
  "bullish": {"directions": ["..."], "sectors": ["..."], "stocks": [{"name": "...", "code": "..."}]},
  "bearish": {"directions": ["..."], "sectors": ["..."], "stocks": [{"name": "...", "code": "..."}]},
  "company_sina": [{"company": "...", "sentiment": "利好|利空", "summary": "..."}],
  "top5_bullish": [{"title": "...", "reason": "..."}]
}"""


def build_analysis_prompt(items: list[dict], date_cn: str) -> str:
    news_json = json.dumps(
        [{"source": it.get("source", ""), "title": it.get("title", ""),
          "content": (it.get("content") or "")[:200]} for it in items],
        ensure_ascii=False)
    return (
        f"今天是{date_cn}。以下是今日抓取的财经新闻(JSON 数组)：\n{news_json}\n\n"
        "请完成：\n"
        "1. 综合影响力/重要性选出 top20（每条给 importance 0-100、sentiment、涉及板块 sectors、"
        "涉及个股 stocks(名称+代码)、一句 reason）；\n"
        "2. 归纳整体利好 bullish 与利空 bearish 的方向 directions、板块 sectors、个股 stocks；\n"
        "3. 对 source 为 sina 的公司类资讯，按公司归类利好/利空，写入 company_sina；\n"
        "4. 从利好中精选 top5_bullish 并给理由。\n\n"
        f"只输出一个 JSON 对象（不要任何其他文字），结构如下：\n{_CONTRACT}"
    )


def parse_analysis_output(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise ValueError("输出中未找到 JSON 对象")
    return json.loads(m.group(0))


def _default_runner(prompt: str, config: dict) -> str:
    cmd = [config.get("claude_command", "claude"), "--print", prompt,
           "--output-format", "text", "--dangerously-skip-permissions"]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                            timeout=config.get("timeout_seconds", 600))
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip()[:500] or "claude CLI 非零退出")
    return result.stdout


def run_analysis(config: dict, conn, runner=None) -> bool:
    runner = runner or _default_runner
    started = datetime.datetime.now()
    date_str = datetime.date.today().strftime("%Y-%m-%d")
    date_cn = datetime.date.today().strftime("%Y年%m月%d日")
    items = db.query_news(conn, date=date_str, limit=500)
    if not items:  # 当天无数据退回最近 200 条
        items = db.query_news(conn, limit=200)
    if not items:
        db.save_analysis_run(conn, started, "error", error="无新闻可分析")
        return False
    try:
        raw = runner(build_analysis_prompt(items, date_cn), config)
        payload = parse_analysis_output(raw)
        db.save_analysis_run(conn, started, "ok", payload=payload)
        logger.info("分析完成：top20=%d 条", len(payload.get("top20", [])))
        return True
    except Exception as e:
        db.save_analysis_run(conn, started, "error", error=str(e)[:1000])
        logger.warning("分析失败: %s", e)
        return False
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_analyzer.py -v`
Expected: PASS（5 passed）

- [ ] **Step 5: 提交**

```bash
git add ainews/analyzer.py tests/test_analyzer.py
git commit -m "feat: Claude 批量分析引擎(prompt/JSON 解析/快照落库)"
```

---

### Task 14: 自选股匹配 + 风险 tag

**Files:**
- Create: `ainews/watch_match.py`
- Test: `tests/test_watch_match.py`

**Interfaces:**
- Consumes: 洞察 payload dict（Task 13 契约）、`db.list_watch` 的行格式
- Produces:
  - `ainews.watch_match.annotate(payload: dict, watch: list[dict]) -> dict`——返回副本：top20 每条追加 `watch_hits: [{"code","name"}]`；顶层追加 `watch_related: [{"code","name","items":[{"title","sentiment"}]}]`

- [ ] **Step 1: 写失败测试**

Create `tests/test_watch_match.py`:
```python
from ainews.watch_match import annotate

PAYLOAD = {"top20": [
    {"title": "招商银行业绩超预期", "sentiment": "利好",
     "stocks": [{"name": "招商银行", "code": "600036"}]},
    {"title": "中芯产能受限", "sentiment": "利空",
     "stocks": [{"name": "中芯国际", "code": "688981"}]},
    {"title": "无关新闻", "sentiment": "中性", "stocks": []},
]}
WATCH = [{"code": "600036", "name": "招商银行", "aliases": ["招行"]}]


def test_annotate_marks_hits_and_related():
    out = annotate(PAYLOAD, WATCH)
    assert out["top20"][0]["watch_hits"] == [{"code": "600036", "name": "招商银行"}]
    assert out["top20"][1]["watch_hits"] == []
    related = out["watch_related"]
    assert len(related) == 1
    assert related[0]["code"] == "600036"
    assert related[0]["items"][0]["sentiment"] == "利好"


def test_annotate_matches_alias_in_title():
    payload = {"top20": [{"title": "招行获批新业务", "sentiment": "利好", "stocks": []}]}
    out = annotate(payload, WATCH)
    assert out["top20"][0]["watch_hits"][0]["code"] == "600036"


def test_annotate_empty_watch_noop():
    out = annotate(PAYLOAD, [])
    assert out["watch_related"] == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_watch_match.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 写实现**

Create `ainews/watch_match.py`:
```python
"""自选股与洞察的文本匹配：命中 name/code/alias 即挂 watch tag。"""
import copy


def _hit(entry_stocks: list[dict], title: str, w: dict) -> bool:
    needles = [w["name"], w["code"], *w.get("aliases", [])]
    for s in entry_stocks:
        if s.get("code") == w["code"] or s.get("name") == w["name"]:
            return True
    return any(n and n in title for n in needles)


def annotate(payload: dict, watch: list[dict]) -> dict:
    out = copy.deepcopy(payload)
    related: dict[str, dict] = {}
    for entry in out.get("top20", []):
        hits = []
        for w in watch:
            if _hit(entry.get("stocks", []), entry.get("title", ""), w):
                hits.append({"code": w["code"], "name": w["name"]})
                rel = related.setdefault(w["code"], {"code": w["code"], "name": w["name"], "items": []})
                rel["items"].append({"title": entry.get("title", ""),
                                     "sentiment": entry.get("sentiment", "中性")})
        entry["watch_hits"] = hits
    out["watch_related"] = list(related.values())
    return out
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_watch_match.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: 提交**

```bash
git add ainews/watch_match.py tests/test_watch_match.py
git commit -m "feat: 自选股匹配与风险标注"
```

---

### Task 15: 洞察页 + 自选股页

**Files:**
- Modify: `ainews/web.py`
- Create: `ainews/templates/insights.html`
- Create: `ainews/templates/watchlist.html`
- Modify: `ainews/templates/base.html`（顶栏加导航）
- Modify: `ainews/static/style.css`（tag 样式）
- Test: `tests/test_web_insights.py`

**Interfaces:**
- Consumes: `db.latest_analysis / list_watch / add_watch / remove_watch`、`watch_match.annotate`
- Produces: 路由 `GET /insights`、`GET /watchlist`、`POST /watchlist/add`（form: code,name,aliases 逗号分隔）、`POST /watchlist/remove`（form: code）

- [ ] **Step 1: 写失败测试**

Create `tests/test_web_insights.py`:
```python
from fastapi.testclient import TestClient
from ainews import db, web
from ainews.cache import QueryCache


def _setup():
    conn = db.get_conn(":memory:")
    db.init_db(conn)
    db.save_analysis_run(conn, __import__("datetime").datetime.now(), "ok", payload={
        "top20": [{"title": "招商银行业绩超预期", "source": "xq", "importance": 90,
                   "sentiment": "利好", "sectors": ["银行"],
                   "stocks": [{"name": "招商银行", "code": "600036"}], "reason": "超预期"}],
        "bullish": {"directions": ["宽松"], "sectors": ["银行"], "stocks": []},
        "bearish": {"directions": [], "sectors": [], "stocks": []},
        "company_sina": [], "top5_bullish": [{"title": "招商银行业绩超预期", "reason": "确定性"}],
    })
    db.add_watch(conn, "600036", "招商银行")
    app = web.create_app(lambda: conn, QueryCache(ttl=1))
    return TestClient(app), conn


def test_insights_renders_top20_and_tags():
    client, _ = _setup()
    r = client.get("/insights")
    assert r.status_code == 200
    assert "招商银行业绩超预期" in r.text
    assert "利好" in r.text          # 情感 tag
    assert "自选" in r.text          # 自选股命中标记


def test_watchlist_page_and_add_remove():
    client, conn = _setup()
    r = client.get("/watchlist")
    assert "招商银行" in r.text
    r = client.post("/watchlist/add", data={"code": "688981", "name": "中芯国际", "aliases": "中芯"},
                    follow_redirects=True)
    assert "中芯国际" in r.text
    r = client.post("/watchlist/remove", data={"code": "688981"}, follow_redirects=True)
    assert "中芯国际" not in r.text
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_web_insights.py -v`
Expected: FAIL（404，路由不存在）

- [ ] **Step 3: 写实现**

Modify `ainews/web.py` —— `create_app` 内追加（`Form` 从 fastapi 导入，`RedirectResponse` 从 fastapi.responses 导入，顶部 `from ainews.watch_match import annotate`）:
```python
    @app.get("/insights", response_class=HTMLResponse)
    def insights(request: Request):
        def producer():
            payload = db.latest_analysis(conn_factory())
            if not payload:
                return None
            return annotate(payload, db.list_watch(conn_factory()))
        data = cache.get_or_set("insights", producer)
        return templates.TemplateResponse("insights.html",
                                          {"request": request, "data": data})

    @app.get("/watchlist", response_class=HTMLResponse)
    def watchlist_page(request: Request):
        conn = conn_factory()
        payload = db.latest_analysis(conn)
        related = annotate(payload, db.list_watch(conn))["watch_related"] if payload else []
        return templates.TemplateResponse("watchlist.html", {
            "request": request, "watch": db.list_watch(conn), "related": related})

    @app.post("/watchlist/add")
    def watchlist_add(code: str = Form(...), name: str = Form(...), aliases: str = Form("")):
        alias_list = [a.strip() for a in aliases.split(",") if a.strip()]
        db.add_watch(conn_factory(), code.strip(), name.strip(), alias_list)
        return RedirectResponse("/watchlist", status_code=303)

    @app.post("/watchlist/remove")
    def watchlist_remove(code: str = Form(...)):
        db.remove_watch(conn_factory(), code.strip())
        return RedirectResponse("/watchlist", status_code=303)
```

Modify `ainews/templates/base.html` 顶栏（`<h1>` 后加导航）:
```html
  <nav class="nav">
    <a href="/">新闻流</a><a href="/insights">当日洞察</a><a href="/watchlist">自选股</a>
  </nav>
```

Create `ainews/templates/insights.html`:
```html
{% extends "base.html" %}
{% block content %}
{% if not data %}<p class="empty">暂无分析结果（等待 08:00/12:00 定时分析或手动运行 analyze）</p>
{% else %}
<section class="panel">
  <h2>🔥 Top5 利好</h2>
  <ol>{% for t in data.top5_bullish %}<li><b>{{ t.title }}</b> — {{ t.reason }}</li>{% endfor %}</ol>
</section>
<section class="panel-row">
  <div class="panel good"><h2>📈 利好</h2>
    <p>方向：{{ data.bullish.directions | join('、') }}</p>
    <p>板块：{{ data.bullish.sectors | join('、') }}</p>
    <p>个股：{% for s in data.bullish.stocks %}{{ s.name }}({{ s.code }}) {% endfor %}</p></div>
  <div class="panel bad"><h2>📉 利空</h2>
    <p>方向：{{ data.bearish.directions | join('、') }}</p>
    <p>板块：{{ data.bearish.sectors | join('、') }}</p>
    <p>个股：{% for s in data.bearish.stocks %}{{ s.name }}({{ s.code }}) {% endfor %}</p></div>
</section>
<section class="panel"><h2>📋 Top20 要闻</h2>
<ul class="news-list">
  {% for it in data.top20 %}
  <li class="news-card">
    <div class="meta"><span class="src">{{ it.source }}</span>
      <span class="tag {{ 'tag-good' if it.sentiment == '利好' else 'tag-bad' if it.sentiment == '利空' else 'tag-neutral' }}">{{ it.sentiment }}</span>
      {% for h in it.watch_hits %}<span class="tag tag-watch">自选·{{ h.name }}</span>{% endfor %}
      <span class="imp">影响 {{ it.importance }}</span></div>
    <div class="title">{{ it.title }}</div>
    <p class="content">{{ it.reason }} ｜ 板块：{{ it.sectors | join('、') }}
      {% if it.stocks %}｜ 个股：{% for s in it.stocks %}{{ s.name }} {% endfor %}{% endif %}</p>
  </li>{% endfor %}
</ul></section>
{% if data.company_sina %}
<section class="panel"><h2>🏢 公司资讯（新浪）</h2>
<ul>{% for c in data.company_sina %}
  <li><span class="tag {{ 'tag-good' if c.sentiment == '利好' else 'tag-bad' }}">{{ c.sentiment }}</span>
      <b>{{ c.company }}</b> — {{ c.summary }}</li>{% endfor %}</ul></section>
{% endif %}
{% endif %}
{% endblock %}
```

Create `ainews/templates/watchlist.html`:
```html
{% extends "base.html" %}
{% block content %}
<section class="panel"><h2>⭐ 我的自选股</h2>
<form class="filters" method="post" action="/watchlist/add">
  <input name="code" placeholder="代码" required>
  <input name="name" placeholder="名称" required>
  <input name="aliases" placeholder="别名(逗号分隔)">
  <button type="submit">添加</button>
</form>
<ul>{% for w in watch %}
  <li>{{ w.name }}（{{ w.code }}）
    <form method="post" action="/watchlist/remove" style="display:inline">
      <input type="hidden" name="code" value="{{ w.code }}"><button>删除</button></form>
  </li>{% else %}<li class="empty">暂无自选股</li>{% endfor %}</ul></section>
<section class="panel"><h2>🔔 自选股相关消息</h2>
<ul>{% for r in related %}
  <li><b>{{ r.name }}</b>
    <ul>{% for it in r.items %}
      <li><span class="tag {{ 'tag-good' if it.sentiment == '利好' else 'tag-bad' if it.sentiment == '利空' else 'tag-neutral' }}">{{ it.sentiment }}</span>{{ it.title }}</li>
    {% endfor %}</ul></li>
  {% else %}<li class="empty">暂无关联消息</li>{% endfor %}</ul></section>
{% endblock %}
```

Modify `ainews/static/style.css` 末尾追加:
```css
.nav { display: flex; gap: 14px; margin-top: 6px; }
.nav a { color: #fff; opacity: .85; text-decoration: none; font-size: 14px; }
.panel { background: #fff; border-radius: 12px; padding: 16px; margin-bottom: 12px;
  box-shadow: 0 1px 3px rgba(0,0,0,.06); }
.panel h2 { font-size: 16px; margin-bottom: 10px; }
.panel-row { display: grid; grid-template-columns: 1fr; gap: 12px; margin-bottom: 12px; }
@media (min-width: 768px) { .panel-row { grid-template-columns: 1fr 1fr; } }
.tag { display: inline-block; padding: 1px 8px; border-radius: 999px; font-size: 12px; }
.tag-good { background: #e6f7ec; color: #16803c; }
.tag-bad { background: #fdeaea; color: #b91c1c; }
.tag-neutral { background: #eef0f3; color: #666; }
.tag-watch { background: #fff7e0; color: #b45309; }
.imp { font-size: 12px; color: #888; }
.filters button { padding: 8px 14px; border: 0; border-radius: 8px;
  background: #b91c1c; color: #fff; }
```

- [ ] **Step 4: 运行测试确认通过（含全量回归）**

Run: `uv run pytest -v`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add ainews/web.py ainews/templates/ ainews/static/style.css tests/test_web_insights.py
git commit -m "feat: 当日洞察页 + 自选股管理页(风险 tag)"
```

---

### Task 16: 分析定时接入 + CLI analyze

**Files:**
- Modify: `ainews/scheduler.py`
- Modify: `ainews/app.py`
- Modify: `ainews/cli.py`
- Modify: `config.json`（新增 `"analysis_times": ["08:00", "12:00"]`）
- Test: `tests/test_scheduler_analysis.py`

**Interfaces:**
- Modify: `ainews.scheduler.start_scheduler(conn_factory, sources, stop_event=None, analysis_job=None, analysis_times=None)`（analysis_job 为无参 callable，在每个 analysis_times 每日执行）
- Produces: CLI 子命令 `analyze`（立即跑一次分析，成功 exit 0）

- [ ] **Step 1: 写失败测试**

Create `tests/test_scheduler_analysis.py`:
```python
import schedule as schedule_lib
from ainews import scheduler


def test_analysis_times_registered(monkeypatch):
    schedule_lib.clear()
    monkeypatch.setattr("ainews.pipeline.run_all", lambda conn, s: [])
    called = []
    import threading
    stop = threading.Event(); stop.set()  # 立即退出循环，只验证注册
    scheduler.start_scheduler(lambda: None, [], stop_event=stop,
                              analysis_job=lambda: called.append(1),
                              analysis_times=["08:00", "12:00"])
    daily = [j for j in schedule_lib.get_jobs() if j.at_time is not None]
    assert len(daily) == 2
    schedule_lib.clear()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_scheduler_analysis.py -v`
Expected: FAIL（`TypeError: start_scheduler() got an unexpected keyword argument 'analysis_job'`）

- [ ] **Step 3: 写实现**

Modify `ainews/scheduler.py` 的 `start_scheduler`:
```python
def start_scheduler(conn_factory, sources: list[dict], stop_event=None,
                    analysis_job=None, analysis_times=None) -> None:
    for s in sources:
        interval = int(s.get("poll_interval", 300))
        schedule.every(interval).seconds.do(
            lambda cfg=s: pipeline.run_source(conn_factory(), cfg))
    if analysis_job and analysis_times:
        for t in analysis_times:
            schedule.every().day.at(t).do(analysis_job)
    # 启动即先跑一轮抓取
    pipeline.run_all(conn_factory(), sources)
    logger.info("调度器启动，%d 个源，%d 个分析定时点",
                len(sources), len(analysis_times or []) if analysis_job else 0)
    while stop_event is None or not stop_event.is_set():
        schedule.run_pending()
        time.sleep(1)
```

Modify `ainews/app.py` 的 `build_app`（调度线程 args 扩展；顶部 `from ainews import analyzer`）:
```python
    if config.get("scheduler_enabled", True) and sources:
        analysis_times = config.get("analysis_times", ["08:00", "12:00"])
        t = threading.Thread(
            target=scheduler.start_scheduler,
            args=(conn_factory, sources),
            kwargs={"analysis_job": lambda: analyzer.run_analysis(config, conn_factory()),
                    "analysis_times": analysis_times},
            daemon=True)
        t.start()
```

Modify `ainews/cli.py`：`sub.add_parser("push", ...)` 之后加：
```python
    sub.add_parser("analyze", help="立即跑一次 Claude 批量分析")
```
`main` 分派处加：
```python
    if args.cmd == "analyze":
        from ainews import analyzer
        conn = _open_conn()
        db.init_db(conn)
        ok = analyzer.run_analysis(_load_config(), conn)
        print("分析完成" if ok else "分析失败，详见 analysis_runs 表")
        return 0 if ok else 1
```

Modify `config.json`：加 `"analysis_times": ["08:00", "12:00"]`。

- [ ] **Step 4: 运行测试确认通过（含全量回归）**

Run: `uv run pytest -v`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add ainews/scheduler.py ainews/app.py ainews/cli.py config.json tests/test_scheduler_analysis.py
git commit -m "feat: 分析定时(08:00/12:00) + CLI analyze 子命令"
```

---

### Task 17: 收尾——合并 + 推送 GitHub

**Files:**
- Modify: `config.json`（确认 `feishu_app_secret` 已清空，值迁 `.env`）
- 无代码变更，纯 git 操作。

**前置安全步骤（MUST，推送前）：**
1. 确认工作区 `config.json` 不再含真实 secret（Task 1 已迁 `.env`）。
2. **历史泄露处理**：`feishu_app_secret` 已存在于历史 commit。推送公共仓库前二选一（问 Human）：
   - a) 提醒 Human 去飞书后台**轮换 app_secret**（推荐，最简单可靠）；
   - b) `git filter-repo` 重写历史抹除该值（重写会改所有 commit hash）。

- [ ] **Step 1: 全量测试 + 端到端验证**

Run: `uv run pytest -v` → 全部 PASS
Run: `uv run python -m ainews.cli serve` → 手机/iPad/PC 宽度检查三个页面。

- [ ] **Step 2: 合并到 main 并推送**

```bash
git config user.email "homcto@gmail.com"
git checkout master
git merge feature/ai-news-redesign --no-ff -m "merge: ai-news 重设计(抓取/分类/存储/展示/分析/自选股)"
git branch -M main
git remote add origin https://github.com/Jawf/ai-news.git
git push -u origin main
```
Expected: push 成功，GitHub 仓库可见 main 分支。

---

## Phase 2 Self-Review

- 当日 Top20 汇总 → Task 13 契约 `top20` + Task 15 渲染 ✅
- 利好/利空 方向+板块+个股归类 → 契约 `bullish`/`bearish` + 洞察页双栏 ✅
- 新浪公司资讯利好/利空归类 → 契约 `company_sina` + prompt 第 3 条 + 洞察页公司段 ✅
- Top5 利好 → 契约 `top5_bullish` + 洞察页置顶 ✅
- 自选股（本地表 + Web 增删）→ Task 12 watchlist + Task 15 页面 ✅
- 自选股关联 + 风险 tag → Task 14 annotate + tag-good/tag-bad/tag-watch 样式 ✅
- 每日 08:00/12:00 批量分析 → Task 16 ✅
- 推送 GitHub(homcto@gmail.com, main) → Task 17（含 secret 历史泄露处理）✅
- 类型一致性：`save_analysis_run/latest_analysis/add_watch/remove_watch/list_watch`（12→13/15）、`annotate`（14→15）、`run_analysis`（13→16）、`start_scheduler` 新签名（16）已核对一致。

## Self-Review

**Spec 覆盖检查：**
- 可配置站点抓取 → Task 1（sources.yaml）+ Task 5（源适配器）+ Task 11（真实源）✅
- 分类 → Task 4 ✅
- 本地数据库设计与存储 → Task 3 ✅
- 响应式 Web（手机/PC/iPad）→ Task 7（CSS 断点 768/1100）✅
- 短缓存 → Task 6 + Task 7（接入）✅
- 飞书推送附加 → Task 9 + Task 10（push 子命令）✅
- 局域网访问 → Task 10（`--host 0.0.0.0`）✅
- 秘钥迁移 .env → Task 1 ✅
- 退役 Tkinter → Task 10 ✅
- 调度 → Task 8 ✅

**Placeholder 扫描：** Task 11 的 `$.<按样本填>` 是抓包后必须由实测数据确定的真实值，已在 Global Constraints 与该任务显式说明「不臆造 endpoint」——属设计约束下的合法待实测项，非计划偷懒占位；其余任务均含完整可运行代码。

**类型一致性：** `NewsItem`、`content_hash`、`get_conn/init_db/upsert_news/query_news/record_fetch_run`、`fetch_source/normalize`、`QueryCache.get_or_set`、`create_app`、`run_source/run_all`、`start_scheduler`、`select_top_n/format_digest/run_push`、`build_app`、`cli.main` 在定义处与消费处签名一致，已核对。
