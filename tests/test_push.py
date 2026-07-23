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
