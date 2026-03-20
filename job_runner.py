"""
job_runner.py - Claude CLI Job Executor
Runs the claude command to collect financial news and send to Feishu
"""

import subprocess
import datetime
import json
import os
import logging
import urllib.request
import urllib.parse

logger = logging.getLogger(__name__)


def _send_via_nanobot(chat_id: str, content: str, log) -> bool:
    """Try sending via nanobot CLI. Returns True on success."""
    try:
        result = subprocess.run(
            ["nanobot", "push", "feishu", chat_id, content],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )
        if result.returncode == 0:
            log("✓ nanobot 发送成功")
            return True
        log(f"✗ nanobot 发送失败 (returncode={result.returncode}): {result.stderr.strip()[:200]}")
        return False
    except FileNotFoundError:
        log("✗ nanobot 命令未找到")
        return False
    except Exception as e:
        log(f"✗ nanobot 异常: {e}")
        return False


def _get_feishu_token(app_id: str, app_secret: str) -> str | None:
    """Get Feishu tenant access token."""
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    payload = json.dumps({"app_id": app_id, "app_secret": app_secret}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())
    if data.get("code") == 0:
        return data["tenant_access_token"]
    return None


def _send_via_feishu_api(config: dict, content: str, log) -> bool:
    """Fallback: send via Feishu open API or webhook. Returns True on success."""
    # Option 1: webhook URL (custom bot)
    webhook_url = config.get("feishu_webhook_url", "").strip()
    if webhook_url:
        try:
            payload = json.dumps({"msg_type": "text", "content": {"text": content}}).encode("utf-8")
            req = urllib.request.Request(
                webhook_url, data=payload, headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
            if data.get("code") == 0 or data.get("StatusCode") == 0:
                log("✓ 飞书 webhook 发送成功")
                return True
            log(f"✗ 飞书 webhook 返回错误: {data}")
        except Exception as e:
            log(f"✗ 飞书 webhook 异常: {e}")

    # Option 2: app_id + app_secret + chat_id
    app_id = config.get("feishu_app_id", "").strip()
    app_secret = config.get("feishu_app_secret", "").strip()
    chat_id = config.get("feishu_chat_id", "").strip()
    if app_id and app_secret and chat_id:
        try:
            token = _get_feishu_token(app_id, app_secret)
            if not token:
                log("✗ 飞书 API 获取 token 失败")
                return False
            # detect receive_id_type by prefix: ou_ = open_id, oc_/og_ = chat_id
            if chat_id.startswith("ou_"):
                id_type = "open_id"
            elif chat_id.startswith("oc_") or chat_id.startswith("og_"):
                id_type = "chat_id"
            else:
                id_type = "chat_id"
            url = f"https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type={id_type}"
            payload = json.dumps({
                "receive_id": chat_id,
                "msg_type": "text",
                "content": json.dumps({"text": content}),
            }).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
            if data.get("code") == 0:
                log("✓ 飞书 API 发送成功")
                return True
            log(f"✗ 飞书 API 返回错误: {data.get('msg')}")
        except Exception as e:
            log(f"✗ 飞书 API 异常: {e}")

    return False


def send_news(config: dict, content: str, log) -> bool:
    """Send news content: try nanobot first, fall back to Feishu API."""
    chat_id = config.get("feishu_chat_id", "")
    log("--- 开始发送到飞书 ---")
    if _send_via_nanobot(chat_id, content, log):
        return True
    log("nanobot 失败，切换到飞书 API 直接发送...")
    return _send_via_feishu_api(config, content, log)


def load_config(config_path: str = None) -> dict:
    if config_path is None:
        config_path = os.path.join(os.path.dirname(__file__), "config.json")
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_prompt(config: dict) -> str:
    today = datetime.date.today().strftime("%Y年%m月%d日")
    template = config.get("claude_prompt_template", "")
    chat_id = config.get("feishu_chat_id", "")
    return template.format(date=today, chat_id=chat_id)


def run_job(config: dict, log_callback=None) -> dict:
    """
    Execute the Claude CLI job.
    Returns: {"success": bool, "output": str, "error": str, "duration": float}
    """
    def log(msg: str):
        logger.info(msg)
        if log_callback:
            log_callback(msg)

    start_time = datetime.datetime.now()
    log(f"[{start_time.strftime('%H:%M:%S')}] 开始执行财经新闻收集任务...")

    try:
        prompt = build_prompt(config)
        claude_cmd = config.get("claude_command", "claude")
        timeout = config.get("timeout_seconds", 600)

        cmd = [
            claude_cmd,
            "--print",
            prompt,
            "--allowedTools", "WebSearch,Bash",
            "--dangerously-skip-permissions",
            "--output-format", "text",
        ]

        log(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] 调用 Claude CLI，超时限制 {timeout}s ...")
        log(f"命令: {' '.join(cmd[:3])} [prompt] ...")

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
            cwd=os.path.dirname(__file__),
        )

        end_time = datetime.datetime.now()
        duration = (end_time - start_time).total_seconds()

        if result.returncode == 0:
            output = result.stdout.strip()
            log(f"[{end_time.strftime('%H:%M:%S')}] ✓ Claude 执行成功，耗时 {duration:.1f}s")
            if output:
                log("--- Claude 输出 ---")
                # Only log first 2000 chars to avoid flooding the UI
                preview = output[:2000] + ("..." if len(output) > 2000 else "")
                for line in preview.splitlines():
                    log(line)
                log("--- 输出结束 ---")
            sent = send_news(config, output, log)
            if not sent:
                log("✗ 所有发送方式均失败，请检查 nanobot 或飞书 API 配置")
            return {"success": sent, "output": output, "error": "" if sent else "发送失败", "duration": duration}
        else:
            err = result.stderr.strip() or result.stdout.strip()
            log(f"[{end_time.strftime('%H:%M:%S')}] ✗ 任务失败 (returncode={result.returncode})")
            log(f"错误信息: {err[:500]}")
            return {"success": False, "output": "", "error": err, "duration": duration}

    except subprocess.TimeoutExpired:
        duration = (datetime.datetime.now() - start_time).total_seconds()
        msg = f"任务超时（超过 {config.get('timeout_seconds', 600)}s）"
        log(f"✗ {msg}")
        return {"success": False, "output": "", "error": msg, "duration": duration}
    except FileNotFoundError:
        duration = (datetime.datetime.now() - start_time).total_seconds()
        msg = f"找不到 claude 命令，请确认已安装 Claude Code CLI 并添加到 PATH"
        log(f"✗ {msg}")
        return {"success": False, "output": "", "error": msg, "duration": duration}
    except Exception as e:
        duration = (datetime.datetime.now() - start_time).total_seconds()
        msg = f"未知错误: {str(e)}"
        log(f"✗ {msg}")
        return {"success": False, "output": "", "error": msg, "duration": duration}
