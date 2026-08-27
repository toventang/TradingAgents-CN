我完成了对当前仓库的只读源码盘点。先明确一个重要边界：

附件不是两个系统的源码，而是一份 Copilot 对话导出，其中描述了：

1. Vibe-Trading
2. Copilot 当时理解的 TradingAgents-CN

因此下面实际比较的是：

- 当前仓库真实代码
- 附件中描述的 Vibe-Trading
- 附件中声称的 TradingAgents-CN

附件中的大量内容不能视为已验证事实，尤其是券商数量、因子数量、回测成熟度和 UI 完整度。

## 一、总体结论

当前项目不是附件里描述的“仅做股票 AI 分析、几乎没有交易系统”的旧版 TradingAgents-CN。它已经加入了因子、策略版本、回测、模拟交易、风险、Campaign、Skills、学习闭环和持久任务等大量新代码。

但当前分支处于一个明显的“模块代码很多，产品集成尚未闭合”的状态：

- 后端共 44 个 router 文件，但只有约 38 个被主应用挂载。
- 前端有 59 个 Vue 页面文件，但路由表只有 20 条，39 个页面未注册。
- 策略、回测、Risk、Skills、Campaign 等新模块前后端文件均存在，但部分后端路由未挂载。
- 持久任务模型、handler 和 worker 之间存在枚举及调用协议不一致。
- Docker 部署没有领域任务 worker。
- 没有实际券商连接器、实盘订单生命周期、期权、期货或加密交易引擎。

所以它目前最准确的定位是：

> 一个以 A/HK/US 股票多智能体研究为核心，正在扩展为因子研究—策略—回测—模拟交易—风控—复盘闭环的平台；研究和数据管理基础较强，但新增量化交易域尚未达到完整可运行产品状态。

分析基线为分支 `jules-J00-baseline-ci-11663274863911267940`，提交 `93ac0fb3`。

## 二、当前项目真实功能模块

| 功能域 | 当前源码能力 | 实际成熟度 |
|---|---|---|
| FastAPI 基础设施 | CORS、TrustedHost、中间件、统一响应、限流、请求 ID、日志 | 较成熟 |
| 认证与用户 | JWT、用户注册登录、密码管理、用户隔离基础 | 旧接口可用；新增接口鉴权接法有问题 |
| 多智能体分析 | LangGraph，市场、基本面、新闻、社交、中国市场分析师，Bull/Bear 辩论、Trader、三类风险辩论与 Risk Judge | 核心能力，最成熟 |
| LLM 接入 | OpenAI、Google、Anthropic及 DeepSeek、DashScope 等兼容适配 | 较完整 |
| 股票数据 | A 股 Tushare/AKShare/BaoStock；港股和美股 provider；行情、K 线、财务数据 | A 股最强，HK/US 次之 |
| 新闻与社交 | 新闻抓取、去重、情绪、重要性、MongoDB 入库、社交数据 | 有实现，但部分 provider 降级函数仍直接返回空 |
| MongoDB | 用户、配置、报告、股票、行情、新闻、财务、日志、任务及新增交易域资源 | 核心数据库 |
| Redis | 分析队列、进度、缓存、通知辅助 | 核心缓存和短期状态层 |
| ChromaDB | 多智能体反思记忆 | 有实现，但不是附件所称的 Session FTS5 |
| 分析任务 | Redis 队列、进度追踪、SSE、WebSocket、报告落库 | 旧分析链路较完整 |
| 数据同步 | 多数据源优先级、降级、一致性检查、调度、历史/财务/新闻同步 | 功能丰富，但 `app/main.py` 启动逻辑过重 |
| 股票筛选 | 基本面、行情、技术条件，数据库优化查询 | 已实现 |
| 自选股与标签 | 用户级自选股、标签、实时刷新 | 已实现 |
| 报告 | 历史查询、Markdown、Word、PDF 导出、Token 统计 | 已实现 |
| 因子平台 | 171 个因子定义、计算器、DAG、PIT 数据、组合因子、因子研究 | 代码较完整 |
| 策略平台 | 14 个系统模板、版本、发布、克隆、回滚、DSL 校验、确定性信号 | 源码存在，后端未挂载 |
| 回测 | 成本/滑点、成交、权益曲线、指标、结果比较 | 代码存在，但任务链路当前不闭合 |
| 模拟交易 | 多币种账户、持仓、订单、A/HK/US 市场识别、费用与 T+1 逻辑 | 已挂载；属于即时成交模拟，不是实盘 broker |
| 风险 | 单股/行业集中度、回撤、VaR、ADV、T+1、涨跌停检查、审计 | 源码存在，路由未挂载 |
| Skills | 版本化 Skill、IO 合约、沙箱、编排、Profile 集成 | 源码存在，路由未挂载 |
| Campaign | 生命周期、周期选股、模拟下单、绩效、风险退出 | 源码存在，但任务类型和部署链路不一致 |
| 学习闭环 | 交易归因、MAE/MFE、反事实、AI 复盘、改进提案 | 服务和页面存在，缺少完整 API 接线 |
| 前端 | Vue 3、Element Plus、Pinia、Axios、ECharts | 页面数量多，但当前路由表严重不完整 |
| Streamlit/CLI | 原有分析、配置、报告和初始化工具 | 遗留兼容层，不应继续扩展 |

核心代码可从 [app](/Z:/Documents/opensource/AI/TradingAgents-CN/app)、[tradingagents](/Z:/Documents/opensource/AI/TradingAgents-CN/tradingagents) 和 [frontend/src](/Z:/Documents/opensource/AI/TradingAgents-CN/frontend/src) 查看。

## 三、与 Vibe-Trading 的核心区别

以下 Vibe-Trading 能力来自附件描述，并未直接核验其源码。

| 维度 | 当前项目 | 附件中的 Vibe-Trading |
|---|---|---|
| 产品入口 | 固定工作流的股票分析与管理后台 | 自然语言通用交易 Agent |
| Agent 范式 | 预定义 LangGraph 分析师、研究员、交易员、风险辩论 | ReAct Agent、动态工具、Session、Skills |
| 市场范围 | 实际主线为 A/HK/US 股票 | 声称覆盖全球股票、加密、期货、期权 |
| 实盘交易 | 没有真实 broker connector | 声称有 IBKR、Alpaca、Robinhood、Tiger、OKX、Binance 等 |
| 模拟交易 | 内置即时成交纸面账户 | Shadow Account 与多 broker 组合 |
| 回测 | 新增日频股票回测，当前链路未完全接通 | 声称有多市场引擎、Walk-Forward、Monte Carlo 等 |
| 因子 | 171 个本地定义 | 声称 452 个 Alpha Zoo 因子 |
| 数据库 | MongoDB + Redis + 文件缓存 + ChromaDB | SQLite、文件 Session、JSONL 审计、CSV Run artifacts、FTS5 |
| UI | Vue 管理后台，页面多但路由集成异常 | React Chat/Run/Portfolio/Alpha Library 风格 |
| 桌面端 | 无 Electron 桌面应用 | 声称有 Electron 和 OS 凭证库 |
| MCP/IM | 未发现完整 MCP server 或 16+ IM 渠道实现 | 附件声称均支持 |
| 风险 | A 股规则和模拟交易前置风控方向较强 | 侧重实盘组合、broker mandate 和审计 |
| 国内适配 | 明显更强：A 股代码、交易日、数据源、中文 LLM、中文 UI | 国内能力只是其多市场体系的一部分 |

本项目相对 Vibe-Trading 的优势是 A 股数据治理、中文模型生态、固定多智能体投研流程、后台运维和 MongoDB 数据管理。

主要劣势是通用 Agent、Session、跨会话检索、实盘交易连接器、全资产类别、桌面端以及研究 Run/artifact 管理。

## 四、当前源码与附件中“TradingAgents-CN”的差异

附件对 TradingAgents-CN 的描述有一部分已经过时，另一部分明显夸大。

### 当前源码比附件描述更强的地方

- 已不再只有 AI 股票分析和自选股。
- 已有 171 因子目录和因子计算服务。
- 已有策略版本、发布、回滚和 14 个系统模板。
- 已有回测模型、成本模型、指标和比较服务。
- 已有用户隔离的模拟交易账户。
- 已有风险引擎、Campaign、学习闭环和 Skills 代码。
- 已有持久任务的租约、心跳、取消、恢复和幂等设计。
- 已有因子、策略、回测、风险、Campaign 等前端页面。

### 附件比实际源码夸大的地方

- “支持加密、期货、期权”：当前主要只是配置分类或文本声明，没有相应交易引擎。
- “完整回测”：代码存在，但 API、TaskType、handler 和 worker 部署未闭合。
- “完整风险 UI”：页面存在，但 Risk router 未挂载。
- “完整策略管理”：页面和服务存在，但 Strategy router 未挂载。
- “完整 Skills”：同样未挂载。
- “完整生产级交易”：没有券商连接器、真实订单状态机、成交回报和账户对账。
- “UI 较完整”：当前路由表只有 20 条，登录、Dashboard、分析、自选股、报告、模拟交易、设置等核心页面都未注册。
- “MongoDB + Redis 双缓存即等价于持久记忆”：当前多智能体长期记忆主要是 ChromaDB，与 Vibe 的 Session/FTS 搜索不是同一种能力。

## 五、当前最严重的集成问题

### P0：前端路由退化

[frontend/src/router/index.ts](/Z:/Documents/opensource/AI/TradingAgents-CN/frontend/src/router/index.ts) 只有 20 条新功能路由，但仓库有 59 个页面文件。

未注册的页面包括：

- 登录
- Dashboard
- 单股/批量/历史分析
- 报告
- 自选股
- 股票筛选
- 模拟交易
- 任务中心
- 数据库、缓存、配置、日志、调度
- 因子研究、组合因子和快照详情
- 404 页面

而 [SidebarMenu.vue](/Z:/Documents/opensource/AI/TradingAgents-CN/frontend/src/components/Layout/SidebarMenu.vue) 仍链接这些路径。当前路由也没有认证守卫或统一布局。

### P0：后端新模块未挂载

[app/main.py](/Z:/Documents/opensource/AI/TradingAgents-CN/app/main.py) 没有挂载：

- `strategies`
- `backtests`
- `skills`
- `campaigns`
- `risk`
- `analysis_profiles`

前端对这些 `/api/...` 接口的调用会得到 404。

### P0：新增接口鉴权依赖错误

新增 routers 使用：

```python
Depends(AuthService.get_canonical_user_id)
```

但 [auth_service.py](/Z:/Documents/opensource/AI/TradingAgents-CN/app/services/auth_service.py) 的这个函数只接收 `TokenData`，没有依赖真实的 Bearer Token 验证函数。

旧接口正确使用的是 [auth_db.py](/Z:/Documents/opensource/AI/TradingAgents-CN/app/routers/auth_db.py) 中从 `Authorization` 请求头解析用户的 `get_current_user`。

此外，回测和风险 router 用可伪造的 `X-User-Role` 请求头判断管理员，不能用于权限控制。

### P0：领域任务类型不一致

[domain_task.py](/Z:/Documents/opensource/AI/TradingAgents-CN/app/models/domain_task.py) 定义的是：

- `FACTOR_COMPUTE`
- `STRATEGY_RUN`
- `BACKTEST`
- `ALERT_EVAL`
- `CAMPAIGN_EVAL`
- `ATTRIBUTION`

但其他代码引用不存在的：

- `BACKTEST_SIMULATION`
- `CAMPAIGN_CYCLE_EXECUTION`

这会造成导入或运行错误。

同时 [domain_worker.py](/Z:/Documents/opensource/AI/TradingAgents-CN/app/workers/domain_worker.py) 按 `handler.execute(...)` 调用，而回测 handler 注册的是 `handle_task` 函数，协议不一致。

### P0：部署没有领域 worker

[docker-compose.yml](/Z:/Documents/opensource/AI/TradingAgents-CN/docker-compose.yml) 只有：

- backend
- frontend
- MongoDB
- Redis
- Redis Commander
- Mongo Express

没有启动 `DomainWorker` 的服务。因此即使提交了因子或回测领域任务，也没有保证存在消费者。

### P1：安全与隐私

- 后端调试日志打印 JWT secret 前缀。
- 前端请求日志打印 Authorization header 前 30 个字符。
- `X-User-Role` 可伪造管理员身份。
- Docker 示例中存在固定 MongoDB、Redis 管理密码，若直接部署会形成风险。
- WebSocket 身份、任务归属和 REST 鉴权存在两套实现，需要统一。

### P1：架构重复

项目同时存在：

- `analysis_service.py` 与约 1900 行的 `simple_analysis_service.py`
- `app/worker.py` 与新的 `app/workers/domain_worker.py`
- 多套 data source manager 和 cache manager
- Vue、Streamlit、CLI 三套 UI
- Redis 分析队列与 MongoDB 领域任务两套任务体系

这增加了状态不一致和维护成本。

## 六、附件所说“缺少哪些 UI”需要重新判断

当前问题不只是“缺少页面”，更首先是“已有页面没有接入产品”。

### 已有源码但当前不可达或后端不可用

- 因子研究、组合因子、因子快照
- 策略目录、版本历史、Diff
- 回测创建、详情、比较
- 风险 Dashboard、审计日志、风险设置
- Skills 目录、编辑、测试
- Campaign 列表、向导、详情
- 交易复盘、学习提案
- 登录、Dashboard、分析、报告、模拟交易和大部分设置页

### 相对 Vibe-Trading 仍真正缺失的 UI

- Chat/Agent Workspace 和 Session 历史
- Run/Artifact 工作区
- 多券商账户连接和组合聚合
- 实盘订单—成交—撤单生命周期
- 实时 P&L 和头寸监控
- 滑点、费用和交易质量分析
- 参数扫描热力图与 Walk-Forward 可视化
- 期权链和 Greeks
- 全资产类别统一搜索
- MCP/工具权限管理
- 审计证据链和合规查询
- 跨 Session 记忆检索

## 七、建议实施顺序

1. 先恢复前端原有路由、布局、登录守卫和 404，再合并新增页面。
2. 统一所有新增 router 的真实 JWT 用户依赖，删除 `X-User-Role` 权限判断。
3. 挂载新 routers，并添加前后端契约测试。
4. 统一 `TaskType`、handler Protocol、注册方式和任务结果落库。
5. 在 Docker Compose 增加独立领域 worker，并验证租约恢复、取消和幂等。
6. 完成后再把策略、回测、风险、Campaign 宣布为正式能力。
7. 最后再考虑实盘 broker、加密、期货、期权和 Vibe 风格的通用 Agent Workspace。

本次没有修改任何文件，也没有运行会依赖数据库、Redis、LLM 或外部数据源的功能测试。工作区原有未提交修改均保持不变。
