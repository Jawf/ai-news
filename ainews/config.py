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
