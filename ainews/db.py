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
