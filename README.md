# 📰 财经新闻 Job 管理器

按配置源周期性抓取财经新闻，提供 Web 新闻流浏览，并可按需将 Top-N 推送到飞书。

---

## 功能概览

- **Web 新闻流**：FastAPI 提供服务端渲染页面 + JSON API，局域网内可访问
- **后台调度采集**：按 `sources.yaml` 各源 `poll_interval` 周期性抓取，失败隔离不影响其他源
- **TTL 查询缓存**：新闻列表查询带缓存，降低重复请求压力
- **飞书推送**：从库中选 Top-N 新闻，格式化后推送到指定飞书群

---

## 项目结构

```
ai-news/
├── pyproject.toml      # uv 项目配置与依赖声明
├── .venv/              # uv 自动创建的虚拟环境
├── ainews/             # 核心包：config/db/fetcher/pipeline/scheduler/web/app/cli
├── job_runner.py       # 飞书发送逻辑（push 模块复用其 send_news）
├── run_once.py         # 无 GUI 单次抓取入口（等价于 `ainews.cli fetch-once`）
├── config.json         # 运行配置（飞书凭证、cache_ttl、scheduler_enabled 等）
├── sources.yaml        # 新闻源适配配置
├── install.bat         # 一键安装脚本
└── logs/               # 运行日志，按日期自动创建
    └── job_YYYYMMDD.log
```

---

## 环境依赖

| 依赖 | 说明 |
|------|------|
| [uv](https://github.com/astral-sh/uv) | Python 包管理器，替代 pip/venv |
| Python 3.12+ | 由 uv 自动管理 |
| [nanobot](https://github.com/nanobot-ai/nanobot)（可选） | `push` 命令优先走 nanobot 发送，未安装时自动回退飞书 Open API |

---

## 快速开始

### 1. 安装 uv（如未安装）

```powershell
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### 2. 安装项目依赖

双击运行 `install.bat`，或在项目目录执行：

```bash
uv sync
```

脚本会自动检查 Claude CLI 和 nanobot 是否可用。

### 3. 启动 Web 服务 + 后台调度

```bash
uv run python -m ainews.cli serve --port 8000
```

浏览器访问 `http://127.0.0.1:8000/` 查看新闻流；局域网内其他设备访问 `http://<本机IP>:8000`（本机 IP 用 `ipconfig` 查看）。`serve` 启动的同时会按 `sources.yaml` 各源 `poll_interval` 在后台线程周期抓取（`config.json` 的 `scheduler_enabled` 可关闭）。

### 4. 手动触发单次抓取（无需常驻服务）

```bash
uv run python -m ainews.cli fetch-once
# 或等价的：
uv run python run_once.py
```

适合配合 **Windows 任务计划程序** 使用，无需保持 `serve` 常驻。

### 5. 推送 Top-N 新闻到飞书

```bash
uv run python -m ainews.cli push -n 10
```

从库中选当日（或最近）Top-N 新闻，格式化后推送到 `config.json` 配置的飞书群。

---

## 配置文件 config.json

```json
{
  "feishu_chat_id": "ou_bfba0b2292e6c00566bcbc688af36fbe",
  "feishu_webhook_url": "",
  "feishu_app_id": "cli_a93dca5ea08d9cc1",
  "feishu_app_secret": "",
  "cache_ttl": 45,
  "scheduler_enabled": true
}
```

| 字段 | 说明 |
|------|------|
| `feishu_chat_id` | 飞书目标群/用户的 chat_id（`push` 推送用） |
| `feishu_webhook_url` | 飞书自定义机器人 webhook（可选，nanobot 失败时的 API 兜底方式之一） |
| `feishu_app_id` / `feishu_app_secret` | 飞书企业自建应用凭证（可选，另一种 API 兜底方式）；`FEISHU_APP_SECRET` 环境变量优先于本字段 |
| `cache_ttl` | Web 新闻流查询缓存 TTL（秒），默认 45 |
| `scheduler_enabled` | `serve` 启动时是否开启后台周期抓取，默认 `true` |

---

## 数据流程

```
sources.yaml（各源 endpoint + JSONPath 映射）
        │
        ▼
  ainews.pipeline.run_all
  逐源抓取 → 分类 → 去重入库 news.db
  （单源失败不影响其他源）
        │
        ├─▶ serve：FastAPI 页面 + /api/news（TTL 缓存）
        │
        └─▶ push：选当日 Top-N → 格式化 → 飞书
              （优先 nanobot，失败回退飞书 Open API/webhook）
```

---

## 飞书消息格式示例

```
📰 2026年03月20日 财经TOP10

1. 【财联社】央行宣布降准0.5个百分点
   摘要：释放长期资金约1万亿元，支持实体经济发展。

2. 【Bloomberg】美联储维持利率不变，暗示年内降息节奏放缓
   摘要：鲍威尔表示将密切关注通胀数据，市场预期降息推迟。

3. 【东方财富】A股三大指数集体上涨，半导体板块领涨
   摘要：沪指涨1.2%，深成指涨1.8%，半导体ETF成交额创新高。

...（共10条）
```

---

## 日志

`ainews.cli` 通过 Python `logging` 输出到标准输出（抓取进度、调度、推送结果）。`logs/` 目录为历史遗留，当前 CLI 不再写入按日期命名的日志文件；如需持久化日志，可自行重定向标准输出，如：

```bash
uv run python -m ainews.cli fetch-once >> logs/fetch.log 2>&1
```

---

## 常见问题

**Q: 启动报错 `找不到 nanobot 命令`**
`push` 会先尝试 nanobot，未安装时自动回退飞书 Open API/webhook（见 `config.json` 的 `feishu_app_id`/`feishu_app_secret`/`feishu_webhook_url`），不影响推送；如需用 nanobot，确认已安装并添加到系统 PATH。

**Q: 想用 Windows 任务计划程序定时抓取**
在任务计划程序中添加触发器（如每天 08:00），操作设置为：
```
程序: uv
参数: run python run_once.py
起始位置: E:\sourceCode\dev\ai\ai-news
```

**Q: 局域网内其他设备访问不了 `http://<本机IP>:8000`**
确认 `serve` 使用的是默认 `--host 0.0.0.0`（而非 `127.0.0.1`），并检查本机防火墙是否放行对应端口。
