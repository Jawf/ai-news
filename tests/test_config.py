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
