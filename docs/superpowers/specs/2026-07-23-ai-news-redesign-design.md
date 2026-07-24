# ai-news 重设计：可配置站点抓取 → 分类 → 本地库 → 响应式 Web 展示

- 日期：2026-07-23
- 状态：已获用户批准（待 spec 复核）
- 分支：`feature/ai-news-redesign`

## 背景与目标

现有 ai-news 是「Tkinter GUI + Claude CLI 采集 + 飞书推送」的单机工具。本次重设计把它改造为：

1. **可配置地从多个站点抓取新闻数据**（首批：tushare.pro/news 的雪球 `xq`、新浪财经 `sina`）；
2. **对数据分类**后**存入本地数据库**；
3. **重新设计响应式 Web 页面**展示，适配手机 / PC / iPad；
4. 展示层做**短暂缓存**；
5. 保留飞书推送能力作为**附加模块**。

## 已确认的关键决策

| 决策点 | 结论 | 说明 |
|--------|------|------|
| 数据获取方式 | **逆向 tushare 网页内部接口** | 不依赖官方 news 接口的积分权限；确切接口地址/响应结构在实现期抓包确认 |
| 现有功能去留 | **飞书推送作为附加保留** | Web 展示为主；旧 Tkinter GUI 退役 |
| 技术栈 | **FastAPI + SQLite + Jinja2 轻量服务端渲染** | 单进程、无前端构建链 |
| 访问场景 | **局域网多设备访问** | 服务监听 `0.0.0.0`，同 WiFi 设备浏览器访问 |
| 分类方式 | **规则关键词分类** | 可配置「关键词→类目」表，离线、可解释 |

## 抓包实测结论（2026-07-24 确认，取代原 JSON 假设）

浏览器实测查明 tushare.pro/news 的真实形态，与最初"内部 JSON 接口"假设不同：

- **服务端渲染 HTML，非 JSON 接口**：`tushare.pro/news/{src}`（xq/sina/...）直接返回含新闻的 HTML。结构：容器 `div.news_data.cur` → 条目 `div.news_item` → `div.news_datetime`（仅 `HH:MM`）+ `div.news_content`（正文）。一次约 1000 条当日快讯，无分页、无独立 JSON 端点。
- **必须携带登录 cookie**：带登录态（cookie `uid`+`username`）返回真实新闻；游客访问只得 Vue 骨架页。抓取程序必须带 tushare 登录 cookie。
- **每条仅 时间 + 正文**：无独立标题、无原文 URL、无源侧 id（正文内【】前缀为标题式）。

**据此确定的抓取实现（用户已批准）**：

- 抓取器扩展支持 `type: html` 源，用 CSS 选择器解析（非 JSONPath）。JSON 适配路径保留、向后兼容。
- HTML 源的 `NewsItem` 映射：`title` = news_content 全文；`content` = 空（快讯即一句话）；`published_at` = 当天日期 + HH:MM；`url`/`external_id` = 空 → `content_hash` 回退 `source|title|published_at` 去重。
- 认证：登录 cookie 存本机 `.env` 的 `TUSHARE_COOKIE`（gitignore，过期手动更新）；`sources.yaml` 的 headers 用 `${TUSHARE_COOKIE}` 占位，运行时从环境注入。
- 回退：cookie 维护不可持续时，可切「直接抓源站」或「官方 API」，只改 `sources.yaml` 该源配置。

## 总体架构

```
[调度器] --每源按间隔--> [抓取器(读源配置)] --> [归一化 + 分类] --> [SQLite 去重入库]
                                                                       |
[局域网设备: 手机/iPad/PC] --HTTP--> [FastAPI + Jinja2 响应式页面] <--(TTL 短缓存)--+
                                                                       |
                                             [每日 Top-N 任务] --> [飞书推送(附加)]
```

单个 Python 进程承载 FastAPI 主体 + 后台调度线程；SQLite 为本地文件库。

## 组件设计

### 1. 抓取层（配置驱动的源适配器）

每个站点是一条适配器配置（`sources.yaml`），抓取器通用、不写死具体源：

```yaml
- id: xq                       # 雪球
  name: 雪球
  enabled: true
  endpoint: "<待抓包确认>"
  method: GET                  # 或 POST
  params: { }
  headers: { }                 # 可能含 cookie/token
  mapping:                     # 响应 JSON → 统一字段（JSONPath）
    list_path: "$.data.items"
    external_id: "$.id"
    time: "$.created_at"
    title: "$.title"
    content: "$.text"
    url: "$.target"
  poll_interval: 300           # 秒
```

- 新增源 = 加一条配置，不改代码；tushare 的 `xq` / `sina` 为头两条。
- **失败隔离**：单个源抓取失败（超时 / 结构变化 / 反爬）不影响其他源，记录到 `fetch_runs` 与日志。
- **归一化**：适配器把响应映射为统一的 `NewsItem`。
- **去重**：按 `content_hash`（source + external_id 或 title+time 的哈希）唯一约束。

### 2. 分类器（规则关键词）

- 可配置的「关键词 → 类目」映射，类目初版：宏观政策 / A股 / 港美股 / 外汇期货 / 公司个股 / 其他。
- 逐条匹配标题 + 正文关键词，命中即打类目；无命中归「其他」。
- 规则表放配置，可随时增补；纯离线、无外部调用。

### 3. 存储（SQLite）

**表 `news`**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增 |
| source | TEXT | 来源 id（xq/sina...） |
| external_id | TEXT | 源侧 id（可空） |
| title | TEXT | 标题 |
| content | TEXT | 正文 |
| url | TEXT | 原文链接 |
| category | TEXT | 分类类目 |
| published_at | DATETIME | 发布时间 |
| fetched_at | DATETIME | 抓取时间 |
| content_hash | TEXT UNIQUE | 去重键 |

索引：`published_at`、`source`、`category`。

**表 `fetch_runs`**：`id` / `source` / `started_at` / `finished_at` / `fetched_count` / `new_count` / `status` / `error`。取代旧 `state.json`；文本日志仍写 `logs/`。

### 4. 调度器

- 后台线程沿用已有的 `schedule` 库（已是项目依赖，避免引新包），按每源 `poll_interval` 轮询抓取入库。
- 随 FastAPI 进程生命周期启动/停止；另保留 `run_once.py` 式的单次抓取入口，便于配 Windows 任务计划或手动触发。

### 5. Web 应用（FastAPI + Jinja2，响应式）

**路由**

- `GET /`：新闻流，支持按**来源 / 类目 / 日期**筛选 + 分页；服务端渲染。
- `GET /api/news`：JSON 接口（给未来的 Kindle 看板 / AJAX 留口）。

**响应式**

- Mobile-first 原生 CSS，断点适配：手机单列卡片流 → iPad 双列 → PC 多列 / 带侧边筛选栏。
- 不引入前端构建链。

**部署**

- 监听 `0.0.0.0:<port>`，局域网设备同 WiFi 直接访问。

### 6. 短缓存

- 进程内 TTL 缓存（cachetools），key = 筛选参数组合，缓存查询/渲染结果。
- TTL 默认 30–60s（可配）。多设备高频刷新不反复砸 DB；新数据最多延迟一个 TTL 可见。

### 7. 飞书推送（附加保留）

- 每日定时任务从近期库里选 Top-N（可选复用现有 Claude 筛选逻辑），推送到飞书群。
- 复用 `config.json` 中的飞书 app 凭证；旧 `job_runner.py` 飞书逻辑抽为独立 push 模块。

## 配置

`config.json` 扩展 / 新增：`sources.yaml`（源适配）、`schedule`、`cache_ttl`、飞书设置、`server.host/port`、分类规则表。

> 安全提醒：现 `config.json` 明文含 `feishu_app_secret`。重设计时应把密钥迁到环境变量或未跟踪的本地文件（`.env`），避免随仓库泄露。

## 错误处理

- 单源失败隔离；网络超时 + 重试退避；响应结构变化导致映射失败则跳过该条并记录。
- 抓取运行状态写 `fetch_runs`，异常写 `logs/`。

## 测试策略

- 单元：分类规则、字段归一化（用抓包录制的样本做 fixture）、去重、缓存 TTL、DB 查询。
- 集成：抓取用 mock HTTP；端到端跑一次「抓取→入库→页面渲染」。

## 迁移

- 旧 Tkinter `main.py` 退役；`job_runner.py` 飞书逻辑保留并抽模块；`logs/` 目录沿用；`state.json` 由 `fetch_runs` 表取代。

## Phase 2：分析洞察层（已获用户批准）

叠加在 Phase 1 底座（抓取→存储→展示）之上的分析子系统。

### 已确认决策

| 决策点 | 结论 |
|--------|------|
| 分析引擎 | Claude AI 批量分析（复用 `claude_command` CLI） |
| 分析时机 | 每日 08:00 与 12:00 各批量一次 |
| 自选股关联 | 按个股名称/代码/别名文本匹配 |
| 自选股维护 | 本地 watchlist 表 + Web 页面增删 |

### 分析引擎

调度器新增两个每日定时点。每次运行：取当日全部新闻 → 拼结构化 prompt 交 Claude CLI → 解析其强制 JSON 输出 → 整份落库为「当日洞察快照」。

**Claude 输出 JSON 契约：**

```json
{
  "top20": [{"title": "...", "source": "xq", "importance": 95,
             "sentiment": "利好|利空|中性", "sectors": ["半导体"],
             "stocks": [{"name": "中芯国际", "code": "688981"}],
             "reason": "一句影响判断"}],
  "bullish": {"directions": ["..."], "sectors": ["..."], "stocks": [{"name": "...", "code": "..."}]},
  "bearish": {"directions": ["..."], "sectors": ["..."], "stocks": [{"name": "...", "code": "..."}]},
  "company_sina": [{"company": "...", "sentiment": "利好|利空", "summary": "..."}],
  "top5_bullish": [{"title": "...", "reason": "..."}]
}
```

覆盖：Top20 汇总、利好方向/板块/个股、利空方向/板块/个股、新浪公司资讯利好/利空、Top5 利好。

### 数据模型（新增）

- **analysis_runs**：`id / run_at / status / error / payload_json`——存整份 Claude 输出，最近一次成功即"当前洞察"，可审计。
- **watchlist**：`id / code(唯一) / name / aliases_json / added_at`。
- Top20 明细从 payload_json 渲染，不拆表（YAGNI）。

### 新浪公司资讯

分析输入中 `source=sina` 条目由 Claude 单独产出公司级利好/利空（`company_sina` 段）。若抓包发现 tushare 有独立新浪"公司"频道，则在 `sources.yaml` 增一条 `sina_company` 源。

### 自选股关联 + 风险 tag

- 渲染时把最新洞察里抽取的个股与 watchlist 的 name/code/aliases 文本匹配，命中即挂风险 tag（利好=绿 / 利空=红）。
- 自选股页单独展示"与我的自选股相关的消息"。
- 不预建全 A 股词典：AI 抽个股，watchlist 提供匹配锚点。

### Web 新增

- `GET /insights`：当日洞察页（Top20 带情感/板块/个股 tag、利好/利空汇总、Top5 利好、新浪公司归类）。
- `GET /watchlist` + `POST /watchlist/add` / `POST /watchlist/remove`：自选股管理与关联消息。
- 复用 Phase 1 响应式 CSS 与 TTL 缓存。

### 依赖方向

Phase 1 底座先行；Phase 2 只读底座数据 + 新增自身表，不反向修改底座契约。

## 组件边界一览

| 组件 | 职责 | 依赖 |
|------|------|------|
| 源适配器 | 按配置抓取 + 归一化 | HTTP 客户端、`sources.yaml` |
| 分类器 | 打类目 | 规则配置 |
| 存储 | 去重入库 + 查询 | SQLite |
| 调度器 | 定时驱动抓取 | 源适配器、存储 |
| Web 应用 | 渲染 + 筛选 + JSON API | 存储、缓存 |
| 缓存 | 短期结果缓存 | 进程内存 |
| 飞书推送 | 每日 Top-N 推送 | 存储、飞书凭证 |
