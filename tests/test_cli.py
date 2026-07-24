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
