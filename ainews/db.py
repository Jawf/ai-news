"""SQLite 存储：news 表 + fetch_runs 表。"""
import datetime
import json
import sqlite3

from ainews.models import NewsItem


def get_conn(db_path: str) -> sqlite3.Connection:
    # check_same_thread=False: ASGI 服务器（TestClient/uvicorn）通过线程池执行同步路由，
    # 单个连接可能被多个线程访问；SQLite 默认编译为线程安全（serialized），可放行。
    conn = sqlite3.connect(db_path, check_same_thread=False)
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
        CREATE TABLE IF NOT EXISTS stock_ref (
            code TEXT PRIMARY KEY,
            name TEXT
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


def bulk_upsert_stock_ref(conn: sqlite3.Connection, rows: list[tuple[str, str]]) -> int:
    """INSERT OR IGNORE 全 A 股代码/名称映射，返回本次实际插入（非重复）的行数。"""
    before = conn.total_changes
    conn.executemany(
        "INSERT OR IGNORE INTO stock_ref (code, name) VALUES (?, ?)", rows
    )
    conn.commit()
    return conn.total_changes - before


def stock_ref_count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM stock_ref").fetchone()[0]


def _normalize_stock_code(code: str) -> str:
    """去掉交易所后缀，如 "600036.SH" -> "600036"。"""
    return code.split(".")[0] if code else code


def find_stock(conn: sqlite3.Connection, code: str | None = None,
                name: str | None = None) -> tuple[str | None, str | None]:
    """按 code 反查 name，或按 name 反查 code；未提供/未命中的一侧为 None。"""
    result_code, result_name = None, None
    if code:
        norm_code = _normalize_stock_code(code)
        row = conn.execute("SELECT name FROM stock_ref WHERE code = ?", (norm_code,)).fetchone()
        result_code = norm_code
        result_name = row["name"] if row else None
    if name:
        row = conn.execute("SELECT code FROM stock_ref WHERE name = ?", (name,)).fetchone()
        result_name = name
        if row:
            result_code = row["code"]
    return result_code, result_name
