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


def test_default_runner_passes_prompt_via_stdin_not_argv(monkeypatch):
    captured = {}

    def fake(cmd, input=None, capture_output=None, text=None, encoding=None, timeout=None):
        captured["cmd"] = cmd
        captured["input"] = input
        class Result:
            returncode = 0
            stdout = "{}"
            stderr = ""
        return Result()

    monkeypatch.setattr(analyzer.subprocess, "run", fake)
    prompt = "这是一个很长的 prompt" * 100
    out = analyzer._default_runner(prompt, {})
    assert out == "{}"
    assert captured["input"] == prompt
    assert prompt not in captured["cmd"]
