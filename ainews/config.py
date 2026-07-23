"""配置加载：config.json（运行参数 + 飞书凭证）与 sources.yaml（源适配）。"""
import json
import os

import yaml

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_dotenv(config_path: str) -> None:
    """若 config_path 同目录存在 .env，解析 KEY=VALUE 行注入 os.environ。

    已存在的环境变量不覆盖（env var 优先级高于 .env）。
    """
    env_path = os.path.join(os.path.dirname(os.path.abspath(config_path)), ".env")
    if not os.path.isfile(env_path):
        return
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if key and key not in os.environ:
                os.environ[key] = value


def load_config(path: str | None = None) -> dict:
    if path is None:
        path = os.path.join(_BASE, "config.json")
    _load_dotenv(path)
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
