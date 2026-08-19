# 功能增强分卷三：实时监控预警与项目运行时 AI Skill 实现规格

> 文档版本：1.0  
> 编写日期：2026-08-17  
> 上位需求：[功能增强.md](./功能增强.md)  
> 公共约束与因子定义：[功能增强-实现级开发规格.md](./功能增强-实现级开发规格.md)

## 1. 功能四：实时监控与预警

### 1.1 范围和“实时”定义

第一阶段使用项目现有行情同步和APScheduler，在交易时段按配置周期批量读取行情、因子、新闻和账户状态：

- A股价格类默认每60秒；用户可配置30..300秒。
- 港股/美股默认每120秒；受数据源限制时自动降低频率。
- 日线因子在收盘数据确认后计算一次。
- 新闻/社交默认每5分钟。
- 组合风险默认每60秒。

这不是交易所逐笔行情。每个预警事件必须显示：

- 行情时间 quote_time。
- 数据获取时间 ingested_at。
- 规则评估时间 evaluated_at。
- 数据源 source。
- 延迟 latency_seconds。
- 数据质量 quality_status。

当延迟超过市场配置阈值时，事件标记stale；stale数据只允许产生“数据延迟”系统预警，不得触发自动交易。

### 1.2 监控对象

scope_type：

- symbol：单股票。
- watchlist：自选股或静态代码列表。
- strategy_universe：发布策略在当日的股票池。
- paper_position：模拟账户当前持仓。
- paper_account：账户和组合指标。
- system：数据源、调度器和worker健康。

规则创建时必须冻结或引用清晰的scope。动态scope每次评估都记录实际symbol集合摘要和universe_snapshot_id。

### 1.3 预警类型

#### 价格

- price_above、price_below。
- pct_change_above、pct_change_below。
- gap_up、gap_down。
- new_high、new_low，窗口5..250。
- limit_up、limit_down。

#### 成交与流动性

- volume_ratio_above。
- amount_above。
- turnover_above。
- liquidity_below。
- no_quote、stale_quote。

#### 技术/因子

- factor_above、factor_below、factor_between。
- factor_cross_up、factor_cross_down。
- factor_rank_enter、factor_rank_exit。
- composite_score_above/below。
- data_quality_changed。

#### 新闻与情绪

- negative_news_detected。
- positive_news_detected。
- news_volume_spike。
- sentiment_cross_threshold。
- high_severity_event；事件分类包括业绩、监管、诉讼、停复牌、分红、回购、减持、重大合同。

#### 模拟账户与持仓

- stop_loss_near、stop_loss_triggered。
- take_profit_near、take_profit_triggered。
- trailing_stop_triggered。
- position_drawdown。
- account_drawdown。
- position_weight_exceeded。
- industry_weight_exceeded。
- cash_below。

#### 系统

- datasource_down。
- datasource_latency。
- factor_job_failed。
- scheduler_job_failed。
- worker_heartbeat_lost。
- notification_delivery_failed。

### 1.4 AlertRule模型

| 字段 | 类型与规则 |
|---|---|
| rule_id | UUID，稳定标识 |
| user_id | 所有者；system规则使用system |
| name/description | 名称和说明 |
| enabled | 布尔 |
| scope | scope_type及其参数 |
| market | CN/HK/US/system |
| trigger | 结构化条件树 |
| evaluation_mode | edge、level、once |
| frequency_seconds | 30..86400 |
| active_schedule | 交易时段、全天或自定义 |
| cooldown_seconds | 默认300，0..604800 |
| recovery_enabled | 是否产生恢复事件 |
| severity | info、warning、critical |
| channels | 第一版只允许in_app、websocket；预留email/webhook |
| action | notify_only、paper_trade；paper_trade仅自动活动内部规则可用 |
| max_events_per_day | 1..1000 |
| expires_at | 可空 |
| state | 最近评估状态摘要 |
| version | 乐观锁版本 |
| created_at/updated_at | UTC时间 |

trigger复用策略条件树，但额外允许：

- current_value与previous_value。
-持续时间 for_seconds或for_evaluations。
- change_rate窗口。

禁止任意表达式。

### 1.5 触发语义

#### edge

条件从false/unknown变为true时触发一次；持续true不重复。恢复到false时若recovery_enabled=true产生recovered事件。

#### level

条件每次为true都可触发，但受cooldown、max_events_per_day和去重控制。

#### once

首次触发后自动禁用规则。

unknown由数据缺失、stale或计算错误产生：

- unknown不能等同false。
- true → unknown不产生恢复。
- unknown → true是否触发由前一确定状态决定。
- 连续unknown达到3个周期时产生一次规则健康告警。

### 1.6 条件评估与状态

每个rule+symbol维护：

- last_value。
- last_condition_state：true/false/unknown。
- true_since、false_since。
- consecutive_true、consecutive_false、consecutive_unknown。
- last_evaluated_at。
- last_triggered_at。
- cooldown_until。
- events_today及其market_date。
- last_event_fingerprint。

事件fingerprint至少包含rule_id、symbol、触发方向、阈值版本和时间桶。MongoDB唯一索引保证并发worker不会重复插入。

规则更新：

- 每次更新version+1。
- 条件、scope、频率或阈值变化后重置状态，但保留事件历史。
- 仅修改名称、描述和channel不重置条件状态。

### 1.7 评估架构

1. APScheduler只创建“评估批次”，不得逐规则创建永久scheduler job。
2. BatchPlanner按market、频率和数据依赖把启用规则分组。
3. QuoteSnapshotLoader每个市场每个周期只取一次行情。
4. FactorSnapshotLoader复用当日已发布快照；没有快照时按规则决定跳过或排队计算，禁止在规则循环内逐股现算。
5. AlertEvaluator纯函数式执行条件。
6. AlertStateRepository采用原子compare-and-set更新状态。
7. EventService先幂等写alert_events，再调用NotificationsService。
8. 评估统计写alert_evaluation_runs。

多个API实例部署时必须使用Redis分布式锁或任务队列保证同一market+frequency+time_bucket只有一个批次执行。锁必须有TTL和owner token，释放时校验owner。

### 1.8 交易时段和非交易日

- market calendar服务提供is_trade_day、sessions、next_open、previous_close。
- 盘中价格规则只在session内运行；午休不运行或降频。
- 收盘规则在close后等待数据确认延迟，A股默认15分钟。
- 周末/节假日只运行新闻、账户和系统规则。
- 美股夏令时必须由时区库处理，不得硬编码北京时间区间。

### 1.9 通知契约

通知type使用alert，metadata必须保留：

- alert_event_id、rule_id、rule_version。
- market、symbol、stock_name。
- trigger_type、severity。
- observed_value、threshold、unit。
- quote_time、evaluated_at、latency_seconds。
- source、quality_status。
- campaign_id/position_id，可空。
- deep_link。

content不得只包含自然语言；前端以metadata生成结构化展示，文本作为降级。

WebSocket消息格式保持type=notification，但服务端必须：

- 从JWT真实sub解析user_id。
- 只给该用户连接发送。
- 不在URL、日志中输出完整token；后续应改为首帧认证或短期ticket。
- 多实例时通过Redis Pub/Sub或Streams把通知转发到持有连接的实例。
- WebSocket不可用时，Mongo通知仍可通过列表补取。

### 1.10 告警数据集合

#### alert_rules

unique(rule_id)，(user_id, enabled, updated_at)，(market, enabled, frequency_seconds)。

#### alert_rule_states

unique(rule_id, scope_key)，其中scope_key为symbol或account；保存状态字段和version。

#### alert_events

- event_id、user_id、rule_id、rule_version。
- scope_key、market、symbol。
- event_type：triggered、recovered、suppressed、evaluation_error。
- observed、threshold、condition_snapshot。
- severity、fingerprint。
- quote_time、evaluated_at、created_at。
- notification_id、delivery_status。

索引：

- unique(fingerprint)
- (user_id, created_at desc)
- (rule_id, created_at desc)
- (symbol, created_at desc)

#### alert_evaluation_runs

run_id、market、frequency、time_bucket、rule_count、symbol_count、triggered_count、unknown_count、duration_ms、source_latency、errors。

### 1.11 预警 API

| 方法与路径 | 行为 |
|---|---|
| POST /api/alerts/rules | 创建规则 |
| GET /api/alerts/rules | 分页查询本人规则 |
| GET /api/alerts/rules/{id} | 规则、状态和最近事件 |
| PUT /api/alerts/rules/{id} | 使用If-Match/version更新 |
| POST /api/alerts/rules/{id}/enable | 启用并执行依赖校验 |
| POST /api/alerts/rules/{id}/disable | 禁用 |
| DELETE /api/alerts/rules/{id} | 软删除；保留事件 |
| POST /api/alerts/validate | 校验条件和scope |
| POST /api/alerts/preview | 用当前快照预览，不写状态、不通知 |
| POST /api/alerts/rules/{id}/test-notification | 发送明确标记的测试通知 |
| GET /api/alerts/events | 按规则、股票、级别、日期分页 |
| POST /api/alerts/events/{id}/ack | 用户确认critical事件 |
| GET /api/alerts/health | 返回批次、延迟、失败和数据源状态 |

错误码：

- ALERT_RULE_NOT_FOUND
- ALERT_RULE_FORBIDDEN
- ALERT_RULE_VERSION_CONFLICT
- ALERT_INVALID_CONDITION
- ALERT_INVALID_SCOPE
- ALERT_DEPENDENCY_UNAVAILABLE
- ALERT_FREQUENCY_TOO_HIGH
- ALERT_QUOTA_EXCEEDED

### 1.12 与自选股兼容

现有favorites中的alert_price_high和alert_price_low继续可读写，但写入时同步为两条AlertRule：

- 规则source=legacy_favorite。
- 用户删除阈值时软删除对应规则。
- 规则事件统一进入alert_events和notifications。
- favorites列表返回legacy字段和rule_id，防止前端产生重复规则。

迁移脚本必须幂等：使用user_id+symbol+legacy_field作为migration_key。

### 1.13 预警前端

- 监控中心：启用规则、触发数、延迟、数据源健康。
- 规则向导：对象 → 类型 → 条件 → 持续时间 → 冷却 → 通知 → 预览。
- 规则列表：启停、健康、上次评估、上次触发、错误。
- 事件中心：实时流、筛选、确认、跳转股票/策略/模拟活动。
- 自选股编辑继续显示高低价预警，并链接高级规则。
- critical预警必须有显著但不阻塞页面的提示；相同fingerprint不得弹窗轰炸。

### 1.14 预警测试与验收

单元测试必须覆盖：

- edge、level、once。
- cooldown、每日上限、恢复事件。
- true/false/unknown转换。
- 条件持续N次。
- 规则更新状态重置。
- 时区、午休、节假日、夏令时。
- stale数据不触发交易。
- 并发评估只产生一个事件。
- 跨用户隔离。
- WebSocket断线后Mongo补取。
- legacy favorites迁移幂等。

验收：

- 在固定行情fixture中，阈值跨越后一个周期内生成一次事件和一次通知。
- 多开两个API实例模拟同一批次，仍只有一个事件。
- 用户A的事件不会发送给用户B。
- 数据源停止更新时产生延迟告警而不是价格买卖告警。

## 2. 功能五：项目运行时 AI Skill 设置

### 2.1 定义

此处Skill指TradingAgents-CN应用内部的“智能体能力配置单元”，不是Codex桌面应用的SKILL.md，也不是允许用户上传并执行任意代码的插件。

Skill由以下内容组成：

- 结构化输入/输出契约。
- 适用智能体角色。
- 可使用的白名单工具。
- 提示词片段和执行步骤。
- 依赖的数据、因子或其他Skill。
- 超时、令牌和调用次数预算。
- 版本、权限和审计信息。

Skill解决“相同分析能力散落在各智能体大段提示词和条件分支中”的问题。

### 2.2 Skill类型

- deterministic：只调用确定性服务，例如因子摘要、风险计算。
- llm_reasoning：调用一个已配置LLM，输入输出有schema。
- composite：按有向无环步骤编排其他Skill。

第一版不支持用户上传Python、Shell、JavaScript、动态包、网络URL工具或任意MCP服务器。

### 2.3 SkillManifest

必填字段：

| 字段 | 说明 |
|---|---|
| skill_id | 稳定标识 |
| version | 整数版本 |
| name/display_name/description | 名称和边界 |
| type | deterministic、llm_reasoning、composite |
| status | draft、published、deprecated、disabled |
| owner | system或user_id |
| visibility | private、shared_readonly、system |
| applicable_agents | market、fundamentals、news、social、bull、bear、research_manager、trader、risk_debators、risk_manager、post_trade_reviewer |
| input_schema | JSON Schema/Pydantic模型引用 |
| output_schema | JSON Schema/Pydantic模型引用 |
| prompt_template_ref | 模板ID和版本，deterministic可空 |
| allowed_tools | ToolRegistry白名单ID |
| dependencies | skill_id+version列表 |
| required_factors | factor_id+version列表 |
| required_data | 数据能力列表 |
| budgets | timeout_seconds、max_llm_calls、max_tool_calls、max_input_tokens、max_output_tokens |
| failure_policy | fail、skip、fallback_skill |
| cache_policy | none、per_symbol_day、per_input_checksum |
| checksum | 发布内容摘要 |

发布后manifest不可修改。

### 2.4 Skill执行契约

SkillExecution输入：

- execution_id、task_id、user_id。
- skill_id、version。
- agent_role。
- market、symbol、as_of。
- validated_inputs。
- context_refs：只保存报告/快照引用。
- model_ref：从AnalysisProfile解析，不含密钥。
- trace_id。

输出：

- status：succeeded、skipped、failed。
- structured_output：必须通过output_schema。
- summary：供后续prompt使用的长度受限文本。
- evidence_refs：因子、行情、新闻、报告的ID和时间。
- warnings。
- usage：LLM tokens、tool_calls、duration、estimated_cost。
- error：脱敏错误。

输出不通过schema时最多一次修复调用；仍失败则按failure_policy处理，不得把半结构化文本伪装成成功。

### 2.5 工具权限

ToolRegistry给每个工具定义：

- tool_id。
- side_effect：read_only或write。
- data_scope：market_data、financial_data、news、factor、paper_account等。
- required_role。
- timeout。
- rate_limit_group。
- input/output schema。

默认Skill只能使用read_only工具。任何write工具必须：

1. 由系统内置Skill声明。
2. 在AnalysisProfile之外单独授权。
3. 执行前生成结构化动作。
4. 由确定性领域服务再次校验。
5. 写审计日志。

第一版所有分析Skill禁止直接下单；自动模拟交易只能由AutomationService根据已发布策略执行。

### 2.6 内置Skill最低目录

| Skill ID | 角色 | 输入 | 结构化输出 |
|---|---|---|---|
| factor_snapshot_summary | market/trader | 因子快照 | 关键因子、排名、贡献、质量 |
| technical_regime | market | OHLCV和技术因子 | trend、momentum、volatility、levels |
| valuation_assessment | fundamentals | 估值和行业横截面 | valuation_state、comparables、warnings |
| financial_quality | fundamentals | 点时财务因子 | profitability、cash_quality、leverage |
| growth_sustainability | fundamentals | 成长因子 | growth_state、stability、red_flags |
| news_event_classifier | news | 新闻列表 | event_type、severity、sentiment、novelty |
| sentiment_aggregation | social/news | 情绪因子 | sentiment、confidence、divergence |
| bull_case_builder | bull | 分析报告 | claims、evidence、catalysts、risks |
| bear_case_builder | bear | 分析报告 | claims、evidence、failure_modes |
| portfolio_risk_plan | risk_manager | 信号和风险因子 | position_limit、stop、take_profit、warnings |
| strategy_explainer | research_manager | 策略信号 | reason_codes解释、主要贡献 |
| backtest_interpreter | research_manager | 回测指标 | strengths、weaknesses、biases、stability |
| trade_loss_attribution | post_trade_reviewer | 完整交易上下文 | cause_codes、evidence、controllability |
| missed_upside_attribution | post_trade_reviewer | 卖出后路径 | exit_quality、counterfactual、cause_codes |
| learning_proposal_generator | post_trade_reviewer | 聚合归因 | 参数建议、证据、风险、验证计划 |

每个内置Skill必须有独立输入/输出模型和golden fixture；不得只是一段没有schema的prompt。

### 2.7 Skill组合

Composite Skill的steps只支持：

- run_skill。
- parallel：无依赖的只读Skill并行。
- select：根据结构化字段选择分支。
- aggregate：确定性合并。

约束：

- 最大20步、嵌套深度5。
- 发布前检查依赖环。
- 并行步骤共享只读上下文，不共享可变字典。
- 任一步骤的输入映射只能引用上游结构化输出，不解析自由文本。

### 2.8 与LangGraph集成

1. TradingAgentsGraph构造时接收ResolvedAnalysisProfile。
2. SkillRegistry解析每个agent_role启用的Skill版本。
3. GraphSetup仍负责节点拓扑；Skill不允许动态插入未知Python节点。
4. 每个分析师节点调用SkillExecutor获得结构化结果，再由统一PromptComposer注入证据摘要。
5. Skill结果写入AgentState新增字段skill_results，键为skill_id@version。
6. 研究经理、交易员和风控经理只消费声明的Skill输出。
7. propagate最终结果保存skill_execution_ids和版本清单。

现有四类分析师的provider特殊分支需逐步收敛到统一执行器；迁移期间没有配置Skill时保持旧行为。

### 2.9 设置优先级

最终启用集合按以下顺序解析：

1. 系统禁用列表：最高优先级，任何用户不可绕过。
2. 策略版本要求的必需Skill。
3. AnalysisProfile显式启用/禁用。
4. 用户默认Skill设置。
5. 系统默认。

若必需Skill被系统禁用，分析/策略运行在开始前失败并返回SKILL_DEPENDENCY_DISABLED。

### 2.10 Skill数据集合

- skill_manifests：unique(skill_id, version)，(owner, status)。
- skill_assignments：unique(user_id, scope_type, scope_id, agent_role)，保存enabled/disabled版本。
- skill_executions：unique(execution_id)，(task_id, created_at)，(user_id, created_at desc)。
- skill_test_cases：系统和用户草稿测试；敏感输入必须脱敏。
- skill_audit_logs：发布、启停、授权、测试和执行异常。

大输出不嵌入manifest；execution只保存受控大小摘要，完整证据通过ref引用。

### 2.11 Skill API

| 方法与路径 | 行为 |
|---|---|
| GET /api/skills/catalog | 可访问的Skill目录 |
| GET /api/skills/{skill_id}/versions/{version} | manifest和依赖 |
| POST /api/skills | 创建用户草稿；只允许配置已有模板和工具 |
| POST /api/skills/validate | schema、权限、依赖、预算校验 |
| POST /api/skills/{id}/test | 使用fixture或单股票沙箱测试 |
| POST /api/skills/{id}/publish | 发布不可变版本 |
| POST /api/skills/{id}/clone | 克隆可见Skill |
| GET /api/skill-assignments | 读取最终和来源分层配置 |
| PUT /api/skill-assignments | 更新用户或Profile范围设置 |
| GET /api/skill-executions | 查询本人执行记录和消耗 |

错误码：

- SKILL_NOT_FOUND
- SKILL_FORBIDDEN
- SKILL_INVALID_SCHEMA
- SKILL_DEPENDENCY_CYCLE
- SKILL_TOOL_NOT_ALLOWED
- SKILL_BUDGET_EXCEEDED
- SKILL_OUTPUT_INVALID
- SKILL_DEPENDENCY_DISABLED

### 2.12 Skill前端

- Skill目录：用途、角色、输入、输出、版本、消耗和状态。
- Skill详情：依赖图、允许工具、提示模板说明、示例输入输出。
- 我的Skill：从模板克隆、配置参数、测试、发布、弃用。
- 分配设置：按用户默认、AnalysisProfile、策略显示最终生效值和来源。
- 执行记录：时长、模型、token、工具次数、状态、证据，不显示密钥和敏感prompt变量。
- 依赖被禁用、版本弃用或预算过高时，在启动分析前阻止并明确提示。

### 2.13 Skill安全和验收

安全测试：

- manifest中出现未知工具、动态模块、URL或代码字段时拒绝。
- 用户不能给自己提升write权限。
- 用户A不能读取用户B私有Skill或execution。
- prompt注入不能改变allowed_tools和budget。
- output schema失败不能进入下游交易决策。
- 日志不包含API Key、JWT或完整账户数据。

功能验收：

- 15个内置Skill均可发现、独立测试并输出有效schema。
- AnalysisProfile选择不同Skill后，执行记录能证明实际采用的精确版本。
- 禁用Skill后新任务不再使用，历史任务仍能复现版本清单。
- 同输入checksum且cache_policy允许时命中缓存，证据时间仍满足as_of。
- 旧分析请求未配置Skill时保持兼容，不因新增系统而失败。

## 3. 建议代码落点

### 3.1 预警

- app/models/alert.py
- app/routers/alerts.py
- app/services/alerts/rule_validator.py
- app/services/alerts/planner.py
- app/services/alerts/evaluator.py
- app/services/alerts/state_repository.py
- app/services/alerts/event_service.py
- app/workers/handlers/alert_evaluation.py
- frontend/src/api/alerts.ts
- frontend/src/types/alert.ts
- frontend/src/views/Alerts/

### 3.2 Skill

- app/models/skill.py
- app/routers/skills.py
- app/services/skills/manifest_service.py
- app/services/skills/assignment_service.py
- tradingagents/skills/registry.py
- tradingagents/skills/loader.py
- tradingagents/skills/executor.py
- tradingagents/skills/tool_registry.py
- tradingagents/skills/builtins/
- frontend/src/api/skills.ts
- frontend/src/types/skill.ts
- frontend/src/views/Skills/

### 3.3 测试

- tests/unit/alerts/
- tests/unit/skills/
- tests/integration/test_alert_api.py
- tests/integration/test_alert_delivery.py
- tests/integration/test_skill_api.py
- tests/integration/test_skill_graph_integration.py
