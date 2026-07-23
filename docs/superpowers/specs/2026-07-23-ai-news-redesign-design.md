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

## 已知风险 / 待实现期确认

- **tushare.pro/news 内部接口的确切形态未确认**：该网页背后很可能调用需登录 session/token 的后端。实现期必须用浏览器 devtools 抓包，确认 endpoint、请求参数、必要的 cookie/token 与响应 JSON 结构。抓取层设计为「配置驱动的源适配器」，用于吸收抓包得到的任意结构；在确认前不臆造接口。
- 若逆向接口不可持续（反爬 / 需登录态难维护），回退选项为「直接抓源站」或「改用官方 API」，届时只需替换 `sources.yaml` 中该源的适配配置。

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
