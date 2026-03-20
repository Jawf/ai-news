# 📰 财经新闻 Job 管理器

每日自动收集 Top 10 财经新闻，通过飞书推送给团队。

---

## 功能概览

- **Windows GUI 管理界面**：实时查看调度状态、执行历史、运行日志
- **定时任务调度**：默认每天 08:00 自动执行，时间可在界面调整
- **多平台新闻采集**：调用 Claude Code CLI，用 WebSearch 覆盖 Bloomberg、Reuters、财联社、东方财富、证券时报、第一财经等主流平台
- **AI 对比筛选**：Claude 综合热度、影响力、时效性，提炼出当日 Top 10 财经新闻
- **飞书自动推送**：通过 `nanobot agent` 将格式化新闻发送到指定飞书群

---

## 项目结构

```
ai-news/
├── pyproject.toml      # uv 项目配置与依赖声明
├── .venv/              # uv 自动创建的虚拟环境
├── main.py             # GUI 管理界面 + 内置调度器
├── job_runner.py       # Claude CLI 任务执行逻辑
├── run_once.py         # 无 GUI 单次执行脚本
├── config.json         # 运行配置（时间、chat_id、prompt 模板等）
├── install.bat         # 一键安装脚本
├── start.bat           # 启动 GUI
└── logs/               # 运行日志，按日期自动创建
    └── job_YYYYMMDD.log
```

---

## 环境依赖

| 依赖 | 说明 |
|------|------|
| [uv](https://github.com/astral-sh/uv) | Python 包管理器，替代 pip/venv |
| Python 3.12+ | 由 uv 自动管理 |
| [Claude Code CLI](https://github.com/anthropics/claude-code) | AI 执行新闻采集与发送 |
| [nanobot](https://github.com/nanobot-ai/nanobot) | 飞书消息推送工具 |

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

### 3. 启动 GUI 管理器

双击 `start.bat`，或执行：

```bash
uv run python main.py
```

### 4. 手动触发单次执行（无 GUI）

```bash
uv run python run_once.py
```

适合配合 **Windows 任务计划程序** 使用，无需保持 GUI 常驻。

---

## GUI 界面说明

```
┌─ 任务状态 ──────────────────────────────────────────┐
│  调度状态: ● 运行中 (每天 08:00)   任务状态: 空闲    │
│  下次执行: 2026-03-21 08:00:00                       │
│  上次执行: 2026-03-20 08:00:02     ✓ 成功  累计: 5次 │
└──────────────────────────────────────────────────────┘
┌─ 设置 ───────────────────────────────────────────────┐
│  执行时间: [08]:[00]    飞书 Chat ID: [ou_xxx...]     │
│  [保存设置]                                           │
└──────────────────────────────────────────────────────┘
[ ▶ 立即运行 ]  [ ⏸ 暂停定时 ]  [ 🗑 清除日志 ]
┌─ 执行日志 ───────────────────────────────────────────┐
│  实时显示 Claude 执行过程与输出                       │
└──────────────────────────────────────────────────────┘
```

| 按钮 | 功能 |
|------|------|
| 立即运行 | 忽略定时，立刻触发一次采集任务 |
| 暂停/开启定时 | 切换定时调度的开关 |
| 清除日志 | 清空界面日志显示区（不影响日志文件） |
| 保存设置 | 保存执行时间和飞书 chat_id，立即生效 |

---

## 配置文件 config.json

```json
{
  "schedule_time": "08:00",
  "schedule_enabled": true,
  "feishu_chat_id": "ou_bfba0b2292e6c00566bcbc688af36fbe",
  "claude_command": "claude",
  "timeout_seconds": 600,
  "log_max_lines": 1000,
  "claude_prompt_template": "..."
}
```

| 字段 | 说明 |
|------|------|
| `schedule_time` | 每日定时执行时间，格式 `HH:MM` |
| `schedule_enabled` | 启动时是否自动开启调度 |
| `feishu_chat_id` | 飞书目标群的 chat_id |
| `claude_command` | claude CLI 命令名，默认 `claude` |
| `timeout_seconds` | 单次任务超时时间（秒），默认 600 |
| `log_max_lines` | 界面日志最大保留行数 |
| `claude_prompt_template` | 发给 Claude 的 prompt，支持 `{date}`、`{chat_id}` 占位符 |

---

## 任务执行流程

```
定时触发 / 手动点击
        │
        ▼
  调用 Claude CLI
  claude --print "<prompt>" \
         --allowedTools "WebSearch,Bash" \
         --dangerously-skip-permissions
        │
        ▼
  Claude 第一步：WebSearch
  搜索各平台今日财经新闻
  (Bloomberg / Reuters / 财联社 /
   东方财富 / 证券时报 / 第一财经 ...)
        │
        ▼
  Claude 第二步：对比筛选
  按热度、影响力、时效性
  提炼 Top 10 财经新闻
        │
        ▼
  Claude 第三步：Bash 执行推送
  nanobot push feishu ou_xxx "<Top 10 内容>"
        │
        ▼
  记录执行结果到 state.json 和日志
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

## 日志文件

每次执行的详细日志保存在 `logs/job_YYYYMMDD.log`，包含：

- 任务启动时间
- Claude CLI 调用命令
- Claude 完整输出
- 执行耗时与成功/失败状态

---

## 常见问题

**Q: 启动报错 `找不到 claude 命令`**
```bash
npm install -g @anthropic-ai/claude-code
```

**Q: 启动报错 `找不到 nanobot 命令`**
确认 nanobot 已安装并添加到系统 PATH。

**Q: 想用 Windows 任务计划程序代替 GUI 常驻**
在任务计划程序中添加触发器（每天 08:00），操作设置为：
```
程序: uv
参数: run python run_once.py
起始位置: E:\sourceCode\dev\ai\ai-news
```

**Q: 修改了 prompt 模板后不生效**
直接编辑 `config.json` 中的 `claude_prompt_template` 字段，下次执行时自动读取，无需重启 GUI。
