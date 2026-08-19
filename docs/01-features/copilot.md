下面我会把“股票分析/选股”这 9 项功能按工程级别、逐步可执行的细化说明全部展开——包括功能目标、用户故事、数据模型（MongoDB 集合与字段）、REST/WS/SSE API 设计、后端服务/模块划分、前端组件与交互、定时任务与 worker、算法/伪代码、AI Skill 与工作流执行引擎设计、回测/模拟引擎、实时监控/预警实现、持久化/缓存/索引、日志/追踪、测试与验收标准、迁移与上线步骤、以及完整的开发任务分解（按优先级和依赖），确保 AI/工程师可以逐步开发实现且不遗漏功能点。

开头先给出总体目标与约束，然后按每项功能逐条展开细化实现细节与步骤。文档面向开发者与 AI（可直接转化为任务、PR、代码生成）。

概览（目标）
- 总目标：在现有 TradingAgents-CN 架构上，新增/完善一套可生产化的“因素与指标并行计算 + 智能选股 + 回测/模拟 + 实时监控/预警 + AI Skill 与工作流设计器 + 复盘/持仓研究”体系，支持批量和单股流程、可配置止盈止损、自动模拟并给出原因分析与学习能力。
- 运行环境：FastAPI 后端（app/），MongoDB 持久化，Redis 缓存/队列，APScheduler 定时任务，worker 异步执行（使用 asyncio/uvicorn），前端 Vue 3（frontend/）。
- 非功能/安全约束：尽量复用现有 services/workers，敏感信息不写入日志；回测/模拟仅做研究（不下单），接口需 rate-limit；长期数据量大，需索引与分片设计。

一、通用约定
- 数据库：在 MongoDB 中新增集合，使用 ISODate 字段、字符串标识符、嵌套文档。
- 所有新 API 统一前缀 /api/analysis（或 /api/strategy、/api/backtest、/api/screening），返回 JSON，错误字段统一： { error: { code, message, request_id } }。
- 后台任务通过 APScheduler 调度并交由 worker（app.worker.*）处理，任务状态写入 backtest_jobs / simulation_jobs / scans_jobs 集合。
- 所有长任务（回测/批量分析/选股）采用任务队列 + SSE/WebSocket 推送进度。
- 配置中心：将新的功能开关放入系统配置（app.services.config_service），并支持 UI 编辑（system config）。

二、数据模型（MongoDB 集合与字段）
为全面、可查询、可回放，以下为建议集合（collection）与字段（必填/可选与索引建议）。

1) collections: factors
- 用途：存储因子定义（可组合、参数化）
- 字段：
  - _id: ObjectId
  - code: string (唯一，如 "MA_20"、"RSI_14" 或 自定义 slug)
  - name: string
  - description: string
  - implementation: enum("builtin","python","sql","llm") — 指示实现方式
  - params: dict — 参数模板（例如 window:20）
  - python_code: string — 若 implementation="python"，存放安全沙箱代码或表达式（参见安全）
  - inputs: list[string] — 依赖列（price, volume, open, close 等）
  - outputs: list[string]
  - tags: [string]
  - created_by, created_at, updated_at
- 索引：code 唯一；tags；created_at

2) collections: factor_results
- 用途：存储某只股票、某日期区间、某因子计算的结果（可缓存）
- 字段：
  - _id
  - factor_code
  - symbol (stock_code)
  - date (ISODate)  — 对每日因子值的时间点
  - value: number | dict
  - window_params: dict
  - computed_at: ISODate
  - source_job_id (可选)
- 索引：factor_code+symbol+date (复合索引)

3) collections: strategies
- 用途：策略定义（选股/交易策略），可包含因子组合、规则、回测参数
- 字段：
  - _id
  - slug: string (唯一)
  - name: string
  - description: string
  - author
  - filters: list[filter_obj] — 选股条件（详见 filter 结构）
  - ranking: { metric: string, direction: "asc"|"desc" } — 排序规则
  - position_sizing: object (percent_of_portfolio, fixed_shares, risk_per_trade)
  - entry_rules: list[rules]
  - exit_rules: list[rules] (含止盈止损设置)
  - backtest_defaults: {start_date, end_date, initial_cash, commission, slippage}
  - enabled: bool
  - created_at, updated_at
- 索引：slug, enabled

filter_obj 示例结构：
- type: enum("factor_threshold","price_pattern","fundamental","llm_filter","script")
- parameters: dict
- logical_operator: "AND"/"OR"（在列表中用于组装）

4) collections: backtest_jobs
- 用途：记录回测任务与结果快照
- 字段：
  - _id (job_id)
  - job_type: "backtest" | "simulation" | "scan"
  - strategy_slug
  - symbols: [string] | "universe_id"
  - start_date, end_date
  - initial_cash, commission, slippage
  - status: enum("queued","running","completed","failed","cancelled")
  - progress: number (0-100)
  - result_summary: { total_return, annualized_return, max_drawdown, sharpe, trades_count }
  - result_time_series: reference to results document or compressed payload location (S3/path) — note: large对象外部存储
  - trades: array of trade objects (or ref)
  - logs: array[string] or ref to log storage
  - created_at, started_at, finished_at, owner
- 索引：status, strategy_slug, created_at

5) collections: simulations (自动选股并模拟)
- 字段：
  - _id
  - job_id (ref backtest_jobs)
  - strategy_snapshot (copied from strategies at run time)
  - pick_date (date when selection happens)
  - selected_symbols: [{symbol,score,ranking_position}]
  - simulation_parameters: { stop_loss_pct, take_profit_pct, max_hold_days, position_sizing }
  - simulation_results: per symbol { entry_date, exit_date, entry_price, exit_price, pnl, reason }
  - learned_insights: array[string]  # 由 AI 分析的亏损/卖飞原因
  - status, progress, created_at
- 索引：pick_date, status

6) collections: alerts
- 用途：推送实时预警、阈值到期、策略触发
- 字段：
  - _id
  - alert_type: enum("price_threshold","indicator_cross","news_alert","llm_alert","system")
  - symbol (nullable)
  - strategy_slug (nullable)
  - severity: enum("info","warning","critical")
  - payload: dict
  - created_at, acknowledged_by, acknowledged_at, sent_channels: [ "sse","email","websocket","sms" ]
  - status: enum("new","sent","acknowledged","resolved")
- 索引：symbol, status, created_at

7) collections: skill_definitions
- 用途：AI Skill 配置与存储（prompt 模板、输入/输出规范、执行策略）
- 字段：
  - _id
  - skill_id (slug)
  - name, description
  - prompt_template (string)  # 支持 Jinja-like placeholders
  - input_schema: JSON Schema
  - output_schema: JSON Schema
  - timeout_seconds
  - model_preferences: list[ { provider, model_name, min_tokens, cost_estimate } ]
  - allow_tool_calls: bool  # 是否允许 tools（例如历史数据检索）
  - created_by, version, created_at
- 索引：skill_id

8) collections: workflow_definitions
- 用途：AI 工作流设计器保存的节点/连线描述（可执行）
- 字段：
  - _id
  - workflow_id / name
  - nodes: [ { id, type, config, nexts } ]  # types: "skill", "if", "loop", "parallel", "http", "script"
  - edges: [ { from, to } ]  # 可视化定序
  - inputs/outputs
  - created_by, created_at, version
- 索引：workflow_id

9) collections: holdings / positions / trades（复盘/持仓研究）
- holdings:
  - _id, symbol, owner_id, avg_cost, qty, opened_at, closed_at, status, tags
- trades:
  - _id, symbol, side, qty, price, timestamp, order_type (simulated), fees, slippage, job_id
- 用于持仓研究、回放、时间序列分析。

三、架构与模块划分（后端）
在 app/ 下按责任添加/修改文件与模块。

主要新增/修改模块（建议路径）
- app/services/
  - factor_service.py  # 统一管理因子定义、注册、计算入口（并行）
  - strategy_service.py # 创建/版本化策略，策略解析器，选股执行器
  - backtest_service.py # 回测引擎入口，接入历史数据、交易规则、结果持久化
  - simulation_service.py # 自动选股并模拟持仓，使用 backtest engine 的轻量模式
  - alert_service.py # 预警触发与发送（SSE/WS/邮件）
  - skill_service.py  # Skill 执行（调用 llm_clients）
  - workflow_service.py # 工作流解析与执行引擎（节点调度）
  - replay_service.py # 复盘研究：收集事件、生成复盘报告
  - holdings_service.py # 持仓/持仓回放 API
- app/routers/
  - analysis_router.py # 因子计算/选股 API
  - strategies_router.py # CRUD 策略 API
  - backtest_router.py # 提交/查询回测
  - simulation_router.py # 自动选股并模拟任务
  - alerts_router.py # 查询/管理告警
  - skills_router.py # Skill 管理与测试端点
  - workflows_router.py # 工作流编辑/执行接口
  - holdings_router.py # 持仓查询/复盘
- app/worker/
  - factor_worker.py # 批量计算因子（并行/分片）
  - backtest_worker.py # 回测任务处理
  - simulation_worker.py # 模拟任务处理
  - alert_worker.py # 监控与告警检测
- tradingagents/（或在 app/services 中）
  - algorithms/portfolio.py # 仓位管理、头寸计算
  - algorithms/indicators.py # 因子实现（MA, EMA, RSI 等）
  - algorithms/backtest_engine.py # 回测核心逻辑（向量化/事件驱动）
  - llm_helpers/skill_runner.py # Skill 封装调用、工具调用代理
- utils / shared
  - job_queue.py # 统一任务队列接口（基于 Redis 列表或 RQ/asyncio）
  - metrics.py # 性能与指标采集（prometheus、statsd 接口）

四、关键设计与算法细节（按功能点展开）

功能 1：因子与指标分析，上百因子的并行计算和分析，以及组合计算分析
- 目标：实现一个可扩展的因子引擎，支持内置因子和用户自定义因子（python 表达式/沙箱脚本/LLM），支持批量并行计算（跨股票、跨时间段）、结果缓存与组合因子（加权、序列组合）。
- 要点：
  - 因子注册（app/services/factor_service.py）
    - API: POST /api/analysis/factors -> 创建因子（code, name, impl, params）
    - GET /api/analysis/factors -> 列表
    - PUT /api/analysis/factors/{code} -> 更新
  - 内置因子库（tradingagents/algorithms/indicators.py）
    - 包含：MA, EMA, RSI, MACD, SMA, Bollinger, ATR, Momentum, Volatility, OBV, ROC, SMA diff, etc.（实现向量化 pandas 接口）
  - 并行计算实现
    - Worker model：APScheduler 提交任务 -> backet tasks 分片（symbols chunking） -> factor_worker 并发运行（asyncio.gather 或 multiprocessing）
    - Pipeline：读取 symbols 列表 -> 对每个 symbol 读取所需历史 OHLCV（QuotesIngestionService 或 data API） -> 以 DataFrame 计算因子 -> 写入 factor_results（批量 upsert）
    - 结果缓存策略：factor_results TTL 可配置；若缓存存在且参数相同则跳过计算
  - 组合因子（composite）
    - 支持通过 SQL-like 或 JSON 配置组合： e.g., composite = "0.4*FACTOR_A + 0.6*FACTOR_B" 或 config {components:[{code,weight},{...}], normalize: true}
    - 组合计算逻辑在 factor_service 提供 compute_composite_factor()
  - 接口
    - POST /api/analysis/compute-factors -> body: { symbols, factor_codes, start_date, end_date, async:true/false, chunk_size }
    - GET /api/analysis/factors/results?symbol=&factor=&start=&end=
  - 性能考虑
    - 批量读取历史数据时使用 bulk queries，减少 DB roundtrip；在 worker 中使用 pandas/numpy 批量运算以加速
    - 对计算高的因子（长窗口）提供分层缓存

功能 2：分析的策略太少  —— 扩展策略库与策略模板
- 目标：提供可复用策略模板（价值/动量/均线/因子混合/新闻驱动/LLM 策略），并提供策略仓库、版本化。
- 要点：
  - 策略 CRUD（app/routers/strategies_router.py）
    - POST /api/strategies
    - GET /api/strategies/{slug}
    - PUT /api/strategies/{slug}
    - DELETE /api/strategies/{slug}
  - 模板库：内置 templates.json（放在 tradingagents/models/templates/）包括：
    - Simple Moving Average Crossover（MA_short/MA_long）
    - RSI Oversold/Overbought
    - Momentum Rank（top N by momentum）
    - Value Factor Combination（PE, PB, ROE）
    - News Momentum（LLM 判别新闻情绪 + 因子）
    - LLM Strategy Example（使用 Skill 执行研究并返回择时决策）
  - 每种模板提供可配置参数说明与默认 backtest 参数
  - 提供“导入策略”功能：将策略从上游（Tauric）吸收或从共享库导入

功能 3：缺少回测（必需：事件驱动或向量化回测）
- 目标：实现一个健壮的回测引擎，支持逐日逐笔事件回放、手续费/slippage/滑点、持仓限制、杠杆、委托类型（市价/限价/条件单）以及交易成本模型。
- 要点：
  - 回测核心（tradingagents/algorithms/backtest_engine.py）
    - 支持两种模式：
      1. 向量化快速模式（适合批量策略剖面，速度快，但对订单细节简化）
      2. 事件驱动精确模式（基于 tick/分钟/日，支持限价订单、部分成交、滑点模型）
  - API
    - POST /api/backtest -> body: { strategy_slug or strategy_payload, symbols, start, end, initial_cash, mode:"vector"|"event", granularity:"daily"|"min", commission, slippage }
    - GET /api/backtest/{job_id} -> 状态/结果
    - GET /api/backtest/{job_id}/download -> 导出报告（CSV/PDF/Markdown/Word）
  - 结果
    - trades list, positions history, equity curve, performance metrics（累计收益、年化、最大回撤、Sharpe、胜率、平均持仓期、平均收益/亏损）
    - 回测报告自动包含图表（Plotly）并可导出为 PDF/Word（使用 python-docx、pdfkit）
  - 存储
    - backtest_jobs 存概要，结果大对象存 reports/ 或上传 S3（或本地 reports/ 目录），并在 DB 保存指针
  - 并行回测
    - 当批量回测多个策略/参数时，使用 worker pool 并发执行，限制资源（CPU、内存）
  - 测试
    - 单元测试覆盖基准策略（已知数据集），对 edge cases（停牌、拆股、除权）做校验

功能 4：缺少实时监控与预警（实时预警）
- 目标：提供实时任务监控、股票价格/因子阈值预警、新闻/LLM驱动事件预警，并支持多渠道推送（SSE、WebSocket、邮件、钉钉/微信/短信）。
- 要点：
  - 监控层
    - metrics: job queue length, running jobs count, worker health, DB connection, latency
    - Prometheus 或自研统计（app/utils/metrics.py）
  - 预警引擎（alert_worker.py & alert_service.py）
    - 定义告警规则（系统规则/用户规则）。用户可通过 UI 配置：
      - 基于价格：price > X 或 price crosses 上/下某值
      - 基于因子：RSI < 30、MA 金叉/死叉、量比 > X
      - 基于策略：策略选股出现 topN 变化、每日报告触发
      - 基于新闻：LLM 判定重大利空/利好
    - 评估频率：实时（SSE/WS 订阅行情），或周期性（每 N 秒/分钟）
    - 通道：SSE（/api/stream/alerts）、WebSocket（/api/ws/alerts）、邮件（SMTP）、第三方 webhook（用户配置）
  - API:
    - POST /api/alerts/rules -> 创建规则
    - GET /api/alerts -> 列表
    - POST /api/alerts/{id}/ack -> 确认
  - 预警去重与抑制（throttling）：设置相同告警最小发送间隔
  - 高可用：将 alert jobs 存入 redis 队列，worker 拉取单独处理，避免重复触发

功能 5：AI缺少SKILL设置（Skill 系统）
- 目标：设计 Skill 概念：一个可复用的有输入/输出 schema、prompt template、执行策略（模型选择、tool调用权限、超时/重试）的元件，供策略/工作流/复盘/分析使用。Skill 支持测试、版本化、权限控制。
- 要点：
  - Skill 定义（collection skill_definitions）
    - fields 如上（prompt_template, input_schema, output_schema, allow_tool_calls, model_preferences）
  - Skill 执行器（app/services/skill_service.py）
    - validate_input(schema)
    - choose_model(model_preferences)  # 根据系统定价/latency选择
    - prepare prompt (render prompt_template with inputs)
    - call llm_clients.run(prompt, timeout)
    - postprocess result (parse JSON, validate output_schema)
  - Tools 支持（allow_tool_calls）
    - Tool types: data_fetch (query historical), run_indicator (compute factor), run_backtest, call_webhook
    - Tool 调用以安全 wrapper 形式由 skill_runner 代理，Skill 需要声明所需 tools（白名单）
  - Skill UI（frontend）：编辑器支持:
    - Prompt 模板编辑（支持占位符）
    - Input/Output JSON Schema 编辑（使用 monaco json schema）
    - 模型偏好与测试面板（允许用 example payload 测试）
  - Integration
    - 在 workflow 节点和策略的“研究分析”步骤调用 Skill（如“分析亏损原因” skill）
  - 安全
    - 限制 skill 执行的工具/系统调用
    - 模板存储与渲染避免命令注入（审计）

功能 6：缺少智能选股自动模拟（含止盈止损、自动分析亏损/卖飞并学习）
- 目标：实现自动选股并从选股日开始模拟下单、设置止盈/止损、持仓管理，并在模拟结束后通过 AI（Skill）分析失败/卖飞原因，输出改进建议与规则更新（半自动）。
- 要点：
  - 流程：
    1. 运行策略（筛选）得到候选池（selected_symbols）
    2. 基于 position_sizing 分配资金并进入 simulation job
    3. 使用 backtest engine 的模拟模式执行“从选股日开始”到 N 天/直到满足退出条件
    4. 收集每笔 trade 的细节与持仓日志
    5. 后处理：基于结果统计胜率/盈亏比/持仓期/卖飞次数（定义：因未及时止盈或提前卖出导致错过收益）
    6. 将失败（亏损或卖飞）样例 feed 到 Skill（分析器）做根因分析（供 AI 生成“原因+修复建议”）
    7. 学习环节：建议策略参数变更或生成新的过滤器（Skill 输出规则），用户确认后可自动创建策略变种并回测
  - Simulation API
    - POST /api/simulations -> body: { strategy_slug, pick_date, stop_loss_pct, take_profit_pct, max_hold_days, capital_per_symbol / position_size_mode, follow_up_rules }
    - GET /api/simulations/{id} -> progress & results
  - 学习与反馈存储
    - learned_insights 存在 simulations 集合
    - suggestions 可转为 candidate strategy patches（stored in strategies_patches collection），等待用户 review
  - 卖飞/亏损原因分析 Skill
    - Input: trade events + symbol historical price series + market context (news)
    - Output: reasons list with labels (e.g., "news_event", "gap_down", "lack_of_stop_loss", "overexposure") + confidence + suggested rule patch
  - 自动化注意点
    - 学习只是建议，必须有“自动应用阈值”配置，否则不会自动修改生产策略
    - 对 AI 输出需要审核流程（UI 提供 accept/reject）

功能 7：AI 工作流设计器（可视化）
- 目标：提供可视化节点/连线的工作流编辑器，节点支持 Skill 调用、条件判断、并行/迭代、HTTP 请求、脚本执行、手动审查等，工作流可保存、版本化、调试、回放。
- 要点：
  - 工作流模型（collection workflow_definitions）
    - Node types:
      - skill: 调用 skill_id，与 input 映射
      - http: 发起 http 请求（可与外部服务集成）
      - if: 条件分支（基于 JS 表达式或 JSONPath）
      - loop: for-each
      - parallel: 多分支执行并收集结果
      - script: 在沙箱中运行 python 脚本（仅特权）
      - manual_approval: 停顿节点等待人工确认
    - 执行引擎（app/services/workflow_service.py）
      - 工作流编译为执行计划（DAG），支持并行执行、错误回滚、超时与重试策略
      - 每个 node 执行后存 ExecutionTrace（用于复盘）
  - 前端
    - 使用现成的可视化库（如 jsPlumb、Rete.js 或 Vue flow）实现“拖拽编辑器”
    - 支持节点属性面板、示例输入、立即运行/调试（step-by-step）
  - API:
    - POST /api/workflows -> 创建
    - POST /api/workflows/{id}/run -> 启动，返回 run_id
    - GET /api/workflows/{id}/runs/{run_id}/trace -> 执行轨迹
  - 权限与审计：保存每次修改的作者、变更日志

功能 8：复盘研究（Replay / Post-mortem）
- 目标：为每次回测/模拟/实盘观测生成可交互的复盘报告，包含关键事件、策略触发点、使用 Skill 生成的可解释分析与建议。
- 要点：
  - 收集：所有 trades、orders、alerts、LLM 分析、news events、position snapshots
  - 复盘报告结构：
    - 概要：绩效指标、关键事件、Top winners/losers
    - 时间轴视图：price chart + trades + news + alerts overlay
    - 深度分析：每笔亏损交易原因（由 Skill）
    - 改进建议列表（可快速生成策略 patch）
  - API:
    - GET /api/replay/{job_id} -> 返回 replay meta + links
    - GET /api/replay/{job_id}/events -> 事件流（用于前端时序展示）
  - 前端：
    - 图表：Plotly 或 Highcharts，overlay trade markers，支持时间轴过滤与事件详情弹窗
    - 导出：PDF/Word

功能 9：持仓研究（Position analytics）
- 目标：分析持仓行为、仓位管理表现、集中度、头寸回撤、换手率等，生成持仓研究报告。
- 要点：
  - 持仓时间序列（每日/分钟快照）：collection positions_snapshots
  - 指标：avg_position_size, max_exposure, turnover, holding_period_distribution, realized_vs_unrealized_pnl
  - 前端：持仓页（单个账户/策略）可过滤时间范围、查看持仓明细 & 下载交易流水
  - API:
    - GET /api/holdings/{owner}/positions?start&end
    - GET /api/analysis/positions/stats?strategy=&owner=

五、API 详表（示例）
注意：每个 endpoint 需实现权限验证（token / user session）与 rate limit。

1) 因子管理
- POST /api/analysis/factors
  - Body: { code, name, description, implementation, params, python_code? }
  - Returns: { ok: true, factor: {...} }
- POST /api/analysis/compute-factors
  - Body: { symbols:[..], factor_codes:[..], start_date, end_date, async:true/false, priority }
  - Returns: { job_id, status }
- GET /api/analysis/factors/results
  - Query: symbol, factor_code, start, end, aggregate (min/max/last)
  - Returns: [{ date, value }]

2) 策略
- CRUD 如上
- POST /api/strategies/{slug}/duplicate -> 复制版本化

3) 回测
- POST /api/backtest
  - Body: { strategy_slug or strategy_payload, symbols, start_date, end_date, initial_cash, mode }
  - Returns: { job_id }
- GET /api/backtest/{job_id}
- GET /api/backtest/{job_id}/report (download link)

4) 自动选股与模拟
- POST /api/simulations
  - Body: { strategy_slug, pick_date, stop_loss_pct, take_profit_pct, position_sizing, max_hold_days, follow_up_analysis:true }
  - Returns: { sim_job_id }
- GET /api/simulations/{sim_job_id}

5) Skill
- POST /api/skills -> create
- POST /api/skills/{id}/test -> body sample_input -> returns model_call_result & parsed_output

6) Workflow
- CRUD + POST run

7) Alerts
- POST /api/alerts/rules
- SSE stream: /api/stream/alerts (订阅实时 alerts)

六、实现细节与伪代码（重点：回测引擎 & 因子并行）

1) 因子并行伪代码（factor_worker.py）
- 输入 job: {job_id, symbols, factor_codes, start_date, end_date, chunk_size}
- 伪代码：
  - chunk_symbols = chunk(symbols, chunk_size)
  - for chunk in chunk_symbols:
      asyncio.create_task(process_chunk(chunk, factor_codes, start_date, end_date))
  - async def process_chunk(chunk, factor_codes, start_date, end_date):
      df_all = fetch_history_bulk(chunk, start_date, end_date)  # returns dict symbol->DataFrame
      results = {}
      for factor_code in factor_codes:
          factor = factor_service.load_factor(factor_code)
          for symbol, df in df_all.items():
              value_series = factor.compute(df, params=factor.params)
              bulk_upsert_to_factor_results(symbol, factor_code, value_series)
- 关键点：
  - fetch_history_bulk：一次从 MongoDB/quotes collection 获取多只证券的历史数据，避免循环 IO
  - compute：对于内置 factor 使用 numpy/pandas 向量化，若使用 python_code，运行于沙箱（见下）
  - bulk_upsert：使用 MongoDB bulk_write

2) 回测（事件驱动）伪代码（backtest_engine）
- 输入： strategy, symbols, start, end, initial_cash, commission, slippage
- 架构：
  - 加载历史数据（按分钟或日）
  - 事件生成器（每个时间点触发 price update、indicator update）
  - 交易函数 evaluate_signals -> 生成 orders -> order matching -> 执行 trades（考虑 slippage/commission）
- 简化伪代码：
  - cash = initial_cash; positions = {}
  - for timestamp in timeline:
      for symbol in universe:
          price = get_price(symbol, timestamp)
          indicators = compute_on_the_fly(symbol, timestamp, strategy)
      signals = strategy.evaluate(indicators, positions, cash)
      for signal in signals:
          order = create_order(signal) # qty or percent
          trade = execute_order(order, price, slippage, commission)
          update_positions(trade)
      record_equity(timestamp, cash, positions)
- 输出 trades list, equity curve，metrics

七、AI / Skill 与学习循环技术细节
- Skill 执行流程：
  1. Validate inputs against input_schema
  2. Render prompt template (Jinja2 safe rendering) with inputs
  3. If allow_tool_calls: prepare tool sandbox and tool stubs
  4. Choose model via model_preferences or cost/latency oracle
  5. Call llm_clients.run(prompt, max_tokens, timeout)
  6. Parse output to JSON (强制 output_schema)
  7. Log call (for cost accounting)、return
- 失败分析 Skill 模板（示例 prompt）
  - 输入: trade_event, price_series(before and after entry), news_snippets, technical_indicators
  - Prompt: “请分析以下亏损交易的可能原因，给出 top-3 原因，并为每个原因给出可量化的过滤器或规则（JSON）用于后续回测。输出格式必须为 JSON:{reasons:[{label,confidence,explanation,suggested_patch}]}.”
- 学习/自动化流程：
  - Skill 分析输出 -> 转化为 candidate_patch (JSON) -> 存 strategies_patches -> 用户在 UI 看到 patch 与回测预估 -> 如果用户 accept，自动将 patch 应用为策略新版本并 enqueue backtest

八、安全性与沙箱
- 禁止任意执行用户上传的 python 代码在主线程。若允许“自定义脚本”：
  - 使用 restricted python sandbox（如 Pyodide/微服务沙箱 / 容器化执行）或把脚本限制为“表达式级别”并使用 numexpr/pandas eval
  - 仅特权账户可运行脚本节点（workflow 节点 script）
- LLM 调用与敏感信息
  - 不在 prompt 中包含明文凭证；若需要上下文数据，用 reference id 并在服务端处理
- 审计
  - 每次 Skill 调用、工作流执行、回测均写 ExecutionTrace 日志（user, timestamp, inputs, outputs, model used, cost）

九、前端设计（Vue 3 + Element Plus）
整体新增页面与组件：
- 因子管理页（FactorList, FactorEditor, FactorCompute）
  - FactorEditor：参数编辑、内置因子模板、测试面板（选择 symbol+range 预览 series）
- 策略页面（StrategyLibrary）
  - templates panel, create/duplicate, edit条件构建器（使用 UI builder 生成 filters）
- 回测页面（BacktestSubmit + BacktestHistory + BacktestReport）
  - 提交回测： strategy 选择/上传、symbols 选择、参数、初始资金
  - Report：Plotly 图表显示 equity curve, trades table, download
- 模拟/自动选股页面（Simulation）
  - 批量运行、查看模拟结果、learned insights（AI 分析）
- 工作流设计器（FlowEditor）
  - 节点库、属性侧栏、run/debug 控制，执行 trace 面板
- Alerts 页面 & SSE/WS 实时面板
  - 实时 alert feed, 规则编辑、ack 管理
- Holdings & Replay 页面
  - 交互式时间轴、事件 overlay、逐笔复盘 modal（含 AI 分析）

前端实现要点：
- 长任务：使用 SSE 或 WebSocket 订阅 /api/stream/jobs/{job_id} 推送进度与日志
- 图表：Plotly 集成，前端请求后端 report JSON 并渲染
- Strategy 条件构建：使用树状 UI 生成 JSON filter_obj

十、测试策略
- 单元测试：因子计算 coverage、backtest deterministic tests（使用已知数据）
- 集成测试：提交回测 -> worker 执行 -> 结果与 reference 比对
- 端到端：UI 提交策略->回测->查看报告
- 性能测试：因子计算在 500/1000 symbols 下的时间基准测试
- 安全测试：script/skill 沙箱攻击模拟

十一、日志/指标/监控
- 每个 long-running job 写入 logs 字段（并上传详细日志到 reports/）
- Prometheus 指标：
  - tradingagents_backtest_jobs_total
  - tradingagents_backtest_running
  - factor_compute_time_seconds (histogram)
  - llm_calls_total and latency, cost_estimate
- 报警：worker failures -> slack/email to admins

十二、配置 / 环境变量（新增）
- ANALYSIS_WORKERS_CONCURRENCY
- FACTOR_CACHE_TTL_DAYS
- BACKTEST_MAX_PARALLEL
- ALERT_DEFAULT_THROTTLE_SECONDS
- SKILL_DEFAULT_TIMEOUT
- SKILL_ALLOW_TOOL_CALLS_BY_DEFAULT (bool)

十三、迁移/部署计划
- 迁移脚本：
  - 创建新的集合（factors, factor_results, strategies, backtest_jobs 等）
  - 将现有部分数据迁移（如果原仓已有策略/因子表）
- 分阶段上线：
  1. 因子引擎 & 内置因子 + 因子 API（基础）
  2. 策略管理 + 向量化回测（快速）
  3. 并行因子批量计算 + 缓存
  4. 精确事件驱动回测
  5. 自动选股模拟 + AI 分析 Skill
  6. 工作流设计器 + 复盘界面 + 持仓研究
  7. 预警引擎与监控集成

十四、验收标准（每项功能）
- 因子引擎：支持至少 50 种内置因子，能对 1000 支股票在 1 天内完成 30 天窗口计算（在给定资源下）
- 回测：能正确处理拆股/除权/停牌情况，回测结果与 baseline 数据差异 < 0.1%
- 自动选股模拟：生成 simulations 结果并给出 learned_insights，建议 patch 在 UI 中可 review
- 工作流：可视化编辑器能创建含 skill node 的 DAG 并成功运行一次（带 trace）
- 预警：规则创建后在 60 秒内能触发至少一次基于实时行情的告警
- 安全：自定义脚本不能越权访问系统资源（测试用例）

十五、开发任务分解（建议 Sprint 列表与估时）
优先级高（Sprint 1-2）
- T1 因子基础库（实现 30 个内置因子）；文件: tradingagents/algorithms/indicators.py （3 dev days）
- T2 因子管理 API + factor_results 存储（app/services/factor_service.py + router）（2 dev days）
- T3 因子并行 worker（app/worker/factor_worker.py）与 bulk history fetch（2 dev days）
- T4 向量化回测快速模式（tradingagents/algorithms/backtest_engine.py）与 API（3 dev days）

中优先（Sprint 3-4）
- T5 策略 CRUD UI + templates（frontend）（2 dev days）
- T6 回测结果 report export（PDF/Word）与绘图（2 dev days）
- T7 Simulation 自动选股基本流程（app/services/simulation_service.py & worker）（3 dev days）

后续（Sprint 5-8）
- T8 精确事件驱动回测（4-6 dev days）
- T9 Skill 系统与 skill_service（3 dev days）
- T10 Workflow 设计器（前端 heavy + backend run engine）（8-12 dev days）
- T11 Alerts 引擎与 SSE/WS（3 dev days）
- T12 复盘/持仓研究 UI（4 dev days）
- T13 安全沙箱实现（审计/容器化/测试）（5 dev days）

十六、验收 / QA 列表（checklist）
- [ ] 新集合的 index 已创建
- [ ] 所有 API 有单元测试
- [ ] 回测引擎有 deterministic test cases
- [ ] Skill 调用有审计日志并受限工具权限
- [ ] 工作流执行有 trace 并可回放
- [ ] 前端组件与样式符合 UI guideline（Element Plus）
- [ ] 性能与资源限制文档化
- [ ] 文档：README 更新、API docs、使用手册（docs/）

十七、示例 payloads（部分）
- 提交回测示例：
  {
    "strategy_slug": "ma_crossover_v1",
    "symbols": ["000001.SZ","000002.SZ"],
    "start_date": "2025-01-01",
    "end_date": "2025-06-30",
    "initial_cash": 100000,
    "mode": "vector",
    "commission": 0.00025,
    "slippage": 0.001
  }
- Skill 测试示例：
  {
    "input": {
      "trade_event": {...},
      "price_series": [...],
      "news_snippets": [...],
      "indicators": {...}
    }
  }

十八、风险与注意点
- 数据质量：历史数据缺失/不一致会严重影响回测结果；需建立数据校验与补齐策略（数据修补策略）。
- 资源消耗：大规模并行回测/因子计算很消耗内存CPU，需作业队列限流。
- LLM 成本：Skill 大量调用会产生成本，需计费/quota 与降级（使用 cheaper model fallback）。
- 合规：强调“仅研究/模拟用途”，避免误导实盘下单。

十九、后续增强建议（未来工作）
- 增加 GPU 加速的回测（如基于 numba / rapids）
- 增强 multi-agent 协同策略（不同 agent 负责选股/择时/风控）
- 模型/策略自动化搜索（AutoML 风格的策略参数优化）
- 对接真实券商 API（严格权限与安全隔离）

二十、逐步实施行动项（最小可交付 MVP 路线图）
- MVP A（2-3 周）：
  - 实现内置因子库（30 因子）
  - factor CRUD & compute API
  - 向量化回测 API + worker + 简单 report
  - 简单策略模板库 & UI（创建/编辑/提交回测）
- MVP B（3-4 周）：
  - 并行因子批处理（worker scaling）
  - Simulation 自动选股并 run（含 stoploss/takeprofit）
  - Skill 基本执行（LLM 调用 + input/output schema）
  - SSE/WS 推送 job 进度
- MVP C（4-6 周）：
  - 精确事件驱动回测
  - 工作流设计器基础（v1）
  - Alerts 引擎与规则 UI
  - Replay/复盘基础界面

结语（如何开始）
1. 确认优先级（是否先做回测还是先做因子并行），建议先做因子+向量化回测（能快速给出结果并验证策略）。
2. 我可以为首个任务（例如实现因子基础库 + 因子计算 API）立刻生成详细的代码草案、数据迁移脚本与测试用例文件清单，并生成 PR 模板。要我先从哪个子任务开始？（例如：1）实现 indicators.py 并添加 unit tests；2）实现 factor_service + router；3）实现 factor_worker 并在 APScheduler 注册）

如果你现在要我继续，我会从你选择的第一项开始：生成具体代码文件清单与每个文件的函数/类骨架（包括 tests、API schemas、Mongo index 创建脚本）并提交下一步实现计划。你想先让 AI/我生成哪个模块的具体代码？