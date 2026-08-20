# TradingAgents-CN《股票分析/选股》全功能开发总规范

> 文档定位：这是面向 AI 编码 Agent / 软件工程团队的**可执行级规格书**。
>
> 本文不是概念方案，不以“功能点描述”为终点，而是把每项能力拆解到：
>
> **目标 → 业务规则 → 数据对象 → 计算规则 → 服务边界 → API → AI Agent/SKILL → 工作流 → 前端页面 → 调度 → 数据一致性 → 异常处理 → 权限 → 性能 → 测试 → 验收标准 → 实施顺序**。
>
> 本文以当前 `toventang/TradingAgents-CN` 的 `main` 分支源码结构为现状基线。当前项目的核心执行链由 `TradingAgentsGraph`、`GraphSetup`、`ConditionalLogic`、`AgentState`、`Propagator`、`AnalysisService` 等组成；新增能力必须兼容现有 LangGraph 多智能体主链，而不是重新复制一套分析引擎。

---

## 0. 开发总目标

### 0.1 最终产品能力

将现有“单股 AI 分析平台”升级为一个完整的：

**因子研究 + 多策略选股 + 回测 + 模拟交易 + 实时监控 + AI Skill + 可视化工作流 + 复盘研究 + 持仓研究平台。**

目标闭环：

```text
数据
 ↓
标准化
 ↓
因子计算
 ↓
指标计算
 ↓
因子组合
 ↓
股票池过滤
 ↓
策略打分 / 排名
 ↓
候选股票
 ↓
AI 深度分析
 ↓
组合/策略生成
 ↓
历史回测
 ↓
自动模拟
 ↓
实时监控
 ↓
预警
 ↓
持仓跟踪
 ↓
复盘
 ↓
归因
 ↓
AI 学习
 ↓
Skill / 策略版本优化
 ↓
再次选股
```

### 0.2 九项需求必须全部实现

| 编号 | 功能 | 必须交付 |
|---|---|---|
| 1 | 因子与指标分析 | 因子注册中心、100+ 因子、并行计算、组合因子、因子分析 |
| 2 | 策略扩展 | 策略 DSL / Strategy SDK、策略市场、参数化、多周期 |
| 3 | 回测 | 事件驱动回测、交易成本、滑点、停牌/涨跌停、复权、防未来函数 |
| 4 | 实时监控预警 | 实时行情、规则引擎、指标触发、策略触发、告警渠道 |
| 5 | AI SKILL | Skill 注册、版本、权限、工具集、提示词、输出契约、评测 |
| 6 | 智能选股自动模拟与学习 | 选股快照、虚拟持仓、止盈止损、卖飞/亏损归因、学习闭环 |
| 7 | AI 工作流设计器 | DAG/Graph 编辑器、节点、条件、循环、运行、调试、版本 |
| 8 | 复盘研究 | 日/周/月复盘、策略复盘、股票复盘、事件归因、AI 总结 |
| 9 | 持仓研究 | 持仓级研究、风险暴露、归因、交易建议、组合层 AI |

---

# 1. 开发总原则

## 1.1 不允许把所有逻辑塞进 `TradingAgentsGraph`

当前 `TradingAgentsGraph` 已承担 LLM Provider、Graph 初始化、工具、Memory、传播等大量职责。新增功能不得继续扩大这个类。

必须新增独立领域层：

```text
tradingagents/
├── agents/
├── graph/
├── dataflows/
├── tools/
├── factor_engine/
├── strategy_engine/
├── backtest/
├── simulation/
├── monitoring/
├── skills/
├── workflows/
├── research/
├── portfolio/
└── learning/
```

Web 层：

```text
app/
├── routers/
├── services/
├── models/
├── worker/
├── core/
└── ...
```

建议新增：

```text
app/services/factor/
app/services/strategy/
app/services/backtest/
app/services/simulation/
app/services/monitoring/
app/services/skills/
app/services/workflow/
app/services/research/
app/services/portfolio/
app/services/learning/
```

---

# 2. 总体领域架构

```text
                           ┌──────────────────────┐
                           │     Vue3 Frontend    │
                           └──────────┬───────────┘
                                      │
                              REST / SSE / WS
                                      │
                           ┌──────────▼───────────┐
                           │      FastAPI         │
                           │ API / Auth / RBAC    │
                           └──────────┬───────────┘
                                      │
        ┌─────────────────────────────┼──────────────────────────────┐
        │                             │                              │
        ▼                             ▼                              ▼
 Factor Domain                  Strategy Domain                AI Domain
        │                             │                              │
        ▼                             ▼                              ▼
 Factor Engine                  Strategy Engine                Skill Engine
        │                             │                              │
        └──────────────────────┬──────┴─────────────┬────────────────┘
                               ▼                    ▼
                         Backtest Engine      Workflow Engine
                               │                    │
                               ▼                    ▼
                         Simulation Engine     Agent Runtime
                               │                    │
                               └──────────┬─────────┘
                                          ▼
                                    Research Engine
                                          │
                              ┌───────────┴───────────┐
                              ▼                       ▼
                       Monitoring Engine        Portfolio Engine
                              │                       │
                              └───────────┬───────────┘
                                          ▼
                                    Learning Engine
                                          │
                                          ▼
                                   Skill / Strategy
```

---

# 3. 数据层统一规范

## 3.1 时间语义

所有行情、因子、策略、回测必须统一：

```text
event_time       = 市场事件发生时间
effective_time   = 指标/因子生效时间
available_time   = 数据真正可被策略使用的时间
trade_date       = 交易日
created_at       = 数据写入时间
updated_at       = 修改时间
```

**任何回测、选股、复盘只能使用 `available_time <= decision_time` 的数据。**

这是整个系统禁止未来函数的第一原则。

---

## 3.2 证券主数据

统一：

```python
Security:
    security_id
    symbol
    exchange
    market
    security_type
    currency
    name
    listed_date
    delisted_date
    board
    lot_size
    price_tick
    status
```

市场：

```text
CN_STOCK
HK_STOCK
US_STOCK
ETF
INDEX
```

后续扩展：

```text
FUND
BOND
OPTION
FUTURE
```

---

## 3.3 行情标准对象

```python
MarketBar:
    security_id
    trade_date
    timestamp
    open
    high
    low
    close
    volume
    amount
    turnover
    prev_close
    adj_factor
    is_suspended
    upper_limit
    lower_limit
```

必须保存原始行情与标准化行情。

---

# 4. 功能一：因子与指标分析系统

# 4.1 产品目标

实现至少 100+ 个可注册、可计算、可组合、可回测验证的因子。

因子按：

```text
价格
成交量
技术指标
动量
波动率
趋势
均线
估值
成长
质量
盈利
财务安全
现金流
营运效率
资金流
市场情绪
事件
新闻情绪
机构行为
行业相对强弱
市场风格
风险因子
组合暴露
```

分类。

---

# 4.2 因子必须具备统一接口

新增：

```text
tradingagents/factor_engine/
├── base.py
├── registry.py
├── context.py
├── executor.py
├── operators.py
├── normalization.py
├── neutralization.py
├── ranking.py
├── combination.py
├── validation.py
└── factors/
    ├── momentum.py
    ├── trend.py
    ├── volatility.py
    ├── volume.py
    ├── valuation.py
    ├── quality.py
    ├── growth.py
    ├── cashflow.py
    ├── sentiment.py
    ├── event.py
    └── market.py
```

统一接口：

```python
class Factor:
    factor_id: str
    name: str
    category: str
    version: str
    frequency: str
    lookback: int

    def compute(self, context: FactorContext) -> FactorResult:
        ...
```

---

# 4.3 因子定义必须包含

```yaml
id:
name:
category:
description:
formula:
inputs:
frequency:
lookback:
direction:
normalization:
neutralization:
winsorization:
missing_policy:
min_history:
supported_markets:
version:
author:
enabled:
cost_level:
```

例：

```yaml
id: momentum.return_20d
name: 20日动量
category: momentum
formula: close[t] / close[t-20] - 1
direction: positive
lookback: 20
frequency: 1d
```

---

# 4.4 因子计算引擎

必须支持：

### 单因子

```text
股票池 × 日期 → 一个数值
```

### 多因子并行

```text
股票池
  ├── factor_001
  ├── factor_002
  ├── ...
  └── factor_200
```

计算原则：

1. 先按数据依赖分层。
2. 同层因子并行。
3. 使用向量化计算优先。
4. 无法向量化才进入线程/进程池。
5. 相同输入不重复加载。
6. 同一日期数据可共享。
7. 相同因子缓存。
8. 失败因子单独记录，不得导致整个任务失败。

---

# 4.5 DAG 因子计算

例如：

```text
close
 ├── return_5d
 ├── return_20d
 ├── return_60d
 └── volatility_20d
       └── risk_adjusted_momentum
```

必须建立：

```python
FactorDependencyGraph
```

执行前拓扑排序。

禁止每个因子重复计算依赖。

---

# 4.6 100+ 因子第一批目录

最低实现：

### 趋势

```text
SMA_5
SMA_10
SMA_20
SMA_60
EMA_12
EMA_26
MACD
MACD_SIGNAL
MACD_HIST
ADX
DI_PLUS
DI_MINUS
Aroon
```

### 动量

```text
ROC_5
ROC_10
ROC_20
ROC_60
MOM_5
MOM_10
MOM_20
RSI_6
RSI_14
RSI_24
STOCH_K
STOCH_D
CCI
Williams_R
TRIX
```

### 波动率

```text
ATR_5
ATR_14
ATR_20
STD_5
STD_10
STD_20
STD_60
realized_vol_5
realized_vol_20
realized_vol_60
downside_vol
beta_20
beta_60
```

### 成交量

```text
VOL_RATIO_5
VOL_RATIO_20
OBV
MFI
CMF
VWAP
VWAP_DISTANCE
TURNOVER_RATIO
AMOUNT_MOMENTUM
```

### 价格形态

```text
DIST_HIGH_20
DIST_LOW_20
POSITION_20
POSITION_60
BREAKOUT_20
BREAKDOWN_20
GAP_UP
GAP_DOWN
BODY_RATIO
UPPER_SHADOW
LOWER_SHADOW
```

### 估值

```text
PE
PB
PS
PCF
EV_EBITDA
DIVIDEND_YIELD
PEG
```

### 成长

```text
REVENUE_GROWTH
PROFIT_GROWTH
EPS_GROWTH
ROE_GROWTH
CASHFLOW_GROWTH
```

### 质量

```text
ROE
ROA
GROSS_MARGIN
OPERATING_MARGIN
NET_MARGIN
ASSET_TURNOVER
INVENTORY_TURNOVER
RECEIVABLE_TURNOVER
DEBT_RATIO
CURRENT_RATIO
QUICK_RATIO
```

### 现金流

```text
OCF
FCF
OCF_MARGIN
FCF_MARGIN
OCF_TO_PROFIT
CAPEX_RATIO
```

### 相对强弱

```text
RELATIVE_RETURN_5
RELATIVE_RETURN_20
RELATIVE_RETURN_60
RELATIVE_STRENGTH_INDEX
INDUSTRY_RELATIVE_STRENGTH
MARKET_RELATIVE_STRENGTH
```

### 情绪/事件

```text
NEWS_SENTIMENT
NEWS_SENTIMENT_CHANGE
SOCIAL_SENTIMENT
SOCIAL_SENTIMENT_CHANGE
ANALYST_UPGRADE_SCORE
ANALYST_DOWNGRADE_SCORE
EARNINGS_SURPRISE
EVENT_RISK_SCORE
```

最终数量以因子注册表统计为准，目标首期不少于 120 个。

---

# 4.7 因子标准化

必须支持：

```text
raw
zscore
rank
percentile
minmax
robust_zscore
winsorized_zscore
```

标准化必须记录：

```text
方法
参数
横截面范围
日期
股票池
```

---

# 4.8 中性化

必须支持：

```text
行业中性
市值中性
行业+市值中性
Beta中性
自定义回归中性
```

模型：

```text
factor = alpha + industry + log_market_cap + beta + epsilon
```

输出 residual。

---

# 4.9 因子组合

支持：

```text
线性加权
rank_sum
equal_weight
ic_weight
icir_weight
risk_adjusted_weight
learned_weight
```

公式：

```text
combined_score =
Σ(weight_i * normalized_factor_i)
```

组合必须版本化。

---

# 4.10 因子分析

每个因子必须自动生成：

```text
IC
Rank IC
IC Mean
IC Std
ICIR
IC t-stat
胜率
分层收益
多空收益
行业暴露
市值暴露
换手率
最大回撤
年度收益
月度收益
稳定性
衰减曲线
```

分组：

```text
Q1
Q2
Q3
Q4
Q5
```

支持：

```text
top-bottom
top 10%
top 20%
bottom 10%
```

---

# 5. 功能二：策略系统

# 5.1 策略必须从代码硬编码变为注册式

新增：

```text
tradingagents/strategy_engine/
├── base.py
├── registry.py
├── universe.py
├── signals.py
├── rules.py
├── position.py
├── risk.py
├── cost.py
├── optimizer.py
└── strategies/
```

---

# 5.2 Strategy 接口

```python
class Strategy:
    strategy_id: str
    version: str

    def select(self, context):
        ...

    def generate_signals(self, context):
        ...

    def rank(self, candidates):
        ...

    def size_positions(self, candidates, portfolio):
        ...

    def risk_check(self, order, portfolio):
        ...

    def exit(self, position, context):
        ...
```

---

# 5.3 必须内置策略

第一阶段至少：

```text
趋势跟踪
均线多头
均线交叉
突破策略
动量策略
反转策略
RSI策略
MACD策略
布林带策略
ATR波动策略
放量突破
缩量回调
高股息
低估值
质量成长
价值成长
PEG
基本面+动量
基本面+技术
多因子排名
行业轮动
市场风格轮动
```

---

# 5.4 策略 DSL

必须支持：

```text
AND
OR
NOT
>
>=
<
<=
BETWEEN
RANK_TOP
RANK_BOTTOM
CHANGE
CROSS_UP
CROSS_DOWN
SUM
AVG
MIN
MAX
PERCENTILE
```

例：

```yaml
entry:
  all:
    - factor: momentum.return_20d
      op: ">"
      value: 0.08
    - factor: technical.rsi_14
      op: "<"
      value: 75
    - factor: valuation.pe
      op: "<"
      value: 40

exit:
  any:
    - stop_loss: -0.08
    - take_profit: 0.20
    - signal:
        factor: technical.macd_hist
        op: "<"
        value: 0
```

---

# 6. 功能三：回测引擎

# 6.1 回测不是简单 DataFrame 买卖

必须实现事件驱动：

```text
MarketEvent
SignalEvent
OrderEvent
FillEvent
PortfolioEvent
RiskEvent
```

流程：

```text
行情
 ↓
Strategy
 ↓
Signal
 ↓
Risk Check
 ↓
Order
 ↓
Execution Simulator
 ↓
Fill
 ↓
Portfolio
 ↓
PnL
 ↓
Metrics
```

---

# 6.2 回测必须支持

```text
股票
ETF
多股票组合
多策略组合
定投
再平衡
资金费率
佣金
印花税
滑点
冲击成本
涨停
跌停
停牌
一字板
无法成交
T+1
最小交易单位
价格最小变动单位
现金约束
融资约束（预留）
```

---

# 6.3 禁止未来函数

每一个：

```text
因子
财务数据
新闻
情绪
选股结果
订单
交易
```

必须带：

```text
available_time
```

回测时：

```python
data.available_time <= decision_time
```

否则拒绝计算并记录：

```text
LOOKAHEAD_BIAS
```

---

# 6.4 回测配置

```yaml
backtest_id:
strategy_id:
strategy_version:
universe:
benchmark:
start_date:
end_date:
initial_cash:
currency:
rebalance_frequency:
execution_frequency:
commission:
stamp_tax:
slippage:
impact:
lot_size:
price_limit:
suspension_rule:
corporate_action:
dividend_rule:
```

---

# 6.5 回测结果

必须输出：

```text
总收益
年化收益
超额收益
Sharpe
Sortino
Calmar
最大回撤
回撤持续时间
胜率
盈亏比
Profit Factor
交易次数
平均持有周期
换手率
资金利用率
手续费占比
滑点损失
Benchmark
Alpha
Beta
Information Ratio
```

并输出：

```text
每日净值
每笔交易
每次持仓
每次调仓
每个行业暴露
每个因子暴露
```

---

# 7. 功能四：实时监控与预警

# 7.1 Monitoring Engine

新增：

```text
tradingagents/monitoring/
├── market_monitor.py
├── factor_monitor.py
├── strategy_monitor.py
├── portfolio_monitor.py
├── alert_engine.py
├── rule_engine.py
└── scheduler.py
```

---

# 7.2 监控对象

```text
股票
指数
因子
策略
组合
持仓
订单
回测运行
AI任务
数据源
```

---

# 7.3 触发器

```text
价格
涨跌幅
成交量
换手率
RSI
MACD
ATR
突破
跌破
因子变化
因子排名变化
策略信号
止盈
止损
回撤
风险暴露
行业集中度
Beta
波动率
新闻情绪
重大事件
财务指标
```

---

# 7.4 告警模型

```python
AlertRule:
    rule_id
    name
    target_type
    target_id
    expression
    frequency
    cooldown
    priority
    enabled
    notify_channels
```

防重复：

```text
cooldown
dedup_key
event_hash
```

---

# 7.5 通知渠道

第一期：

```text
站内通知
SSE
WebSocket
邮件
```

第二期可扩展：

```text
企业微信
钉钉
Telegram
Webhook
```

---

# 8. 功能五：AI SKILL 系统

## 8.1 Skill 不是 Prompt

Skill 是一个完整可执行能力包：

```text
Skill
├── metadata
├── system_prompt
├── instructions
├── tools
├── input_schema
├── output_schema
├── permissions
├── examples
├── validators
├── evaluator
├── version
└── lifecycle
```

---

# 8.2 Skill 目录

新增：

```text
tradingagents/skills/
├── base.py
├── registry.py
├── loader.py
├── validator.py
├── executor.py
├── evaluator.py
└── builtin/
    ├── stock_analysis/
    ├── factor_research/
    ├── strategy_design/
    ├── backtest_analysis/
    ├── portfolio_research/
    ├── postmortem/
    ├── risk_analysis/
    └── stock_screening/
```

---

# 8.3 Skill Manifest

```yaml
id: factor_research
name: 因子研究
version: 1.0.0
description:
input_schema:
output_schema:
tools:
permissions:
model_profile:
temperature:
max_tokens:
timeout:
requires:
```

---

# 8.4 Skill 权限

必须限制：

```text
read_market_data
read_factor_data
read_portfolio
write_strategy
run_backtest
run_simulation
create_alert
modify_workflow
write_memory
```

AI 不能直接绕过权限执行。

---

# 8.5 Skill 输出契约

禁止“只输出自然语言”。

必须：

```json
{
  "summary": "...",
  "findings": [],
  "evidence": [],
  "actions": [],
  "confidence": 0.0,
  "risks": [],
  "next_steps": []
}
```

---

# 9. 功能六：智能选股自动模拟 + 学习闭环

这是整个项目最重要的新增闭环。

# 9.1 核心思想

不是：

```text
今天选股
→ 看看结果
```

而是：

```text
T0：
策略/AI 选出股票

T0：
记录真实可见数据快照

T0：
生成虚拟订单

T+1...
实时更新

触发：
止盈 / 止损 / 信号退出 / 时间退出

最终：
计算真实可实现收益

然后：
AI 分析为什么赚钱/亏钱/卖飞

再：
生成经验

最后：
沉淀到 Skill / Memory / Strategy Version
```

---

# 9.2 Screening Snapshot

必须记录：

```text
screening_id
timestamp
market
universe
strategy_id
strategy_version
factor_snapshot
rank
score
AI_reasoning
price_at_selection
volume_at_selection
risk_at_selection
```

不能只保存股票代码。

---

# 9.3 Simulation Position

```python
SimulationPosition:
    position_id
    simulation_id
    security_id
    entry_time
    entry_price
    quantity
    stop_loss_price
    take_profit_price
    trailing_stop
    max_holding_days
    exit_time
    exit_price
    exit_reason
    realized_pnl
    realized_return
```

---

# 9.4 支持止盈止损

### 固定止损

```text
entry_price * (1 - stop_loss_pct)
```

### 固定止盈

```text
entry_price * (1 + take_profit_pct)
```

### 移动止盈

```text
highest_price * (1 - trailing_pct)
```

### 分级止盈

```text
+10% → 卖 25%
+20% → 卖 25%
+30% → 卖 25%
剩余 → trailing stop
```

---

# 9.5 特殊市场规则

回测/模拟必须考虑：

```text
涨停无法卖出
跌停无法买入
停牌无法交易
T+1
最低交易单位
复权
除权除息
开盘跳空
集合竞价
```

否则结果不得标记为“可交易模拟”。

---

# 9.6 卖飞识别

定义：

```text
actual_exit_price < future_max_price
```

统计：

```text
exit_price
future_5d_high
future_10d_high
future_20d_high
future_60d_high
missed_upside
```

判定：

```text
missed_upside >= threshold
```

进入：

```text
SELL_TOO_EARLY
```

---

# 9.7 亏损归因

至少识别：

```text
选择错误
因子失效
行业错误
市场环境错误
数据延迟
AI误判
信号滞后
止损过紧
止盈过早
仓位过大
交易成本过高
滑点过高
极端事件
```

---

# 9.8 学习闭环

必须生成：

```text
Outcome
 ↓
Attribution
 ↓
Lesson
 ↓
Memory
 ↓
Skill Evaluation
 ↓
Strategy Improvement Proposal
 ↓
Human Approval
 ↓
New Strategy Version
```

默认禁止 AI 自动直接修改生产策略。

必须：

```text
Draft → Evaluate → Approve → Activate
```

---

# 10. 功能七：AI 工作流设计器

## 10.1 定位

允许用户拖拽生成：

```text
数据
→ 因子
→ 选股
→ AI 分析
→ 回测
→ 模拟
→ 监控
→ 复盘
```

---

# 10.2 Workflow Node 类型

```text
INPUT
DATA
FACTOR
FILTER
RANK
STRATEGY
AI_AGENT
SKILL
BACKTEST
SIMULATION
MONITOR
ALERT
LOOP
CONDITION
MERGE
SPLIT
TRANSFORM
SCHEDULE
WEBHOOK
OUTPUT
```

---

# 10.3 Workflow Graph

使用 DAG 为主，允许条件分支和有限循环。

节点：

```python
WorkflowNode:
    node_id
    type
    name
    config
    input_schema
    output_schema
    retry_policy
    timeout
```

Edge：

```python
WorkflowEdge:
    source
    target
    condition
```

---

# 10.4 示例工作流

```text
[每日9:00]
    ↓
[更新行情]
    ↓
[计算120因子]
    ↓
[行业中性]
    ↓
[多因子排名]
    ↓
[TOP 50]
    ↓
[AI 基本面 Skill]
    ↓
[AI 风险 Skill]
    ↓
[评分]
    ↓
[TOP 10]
    ├──→ [通知]
    └──→ [模拟开仓]
              ↓
        [实时监控]
              ↓
       [止盈/止损]
              ↓
          [复盘]
```

---

# 10.5 Workflow Runtime

必须支持：

```text
create
validate
compile
run
pause
resume
cancel
retry
replay
debug
version
clone
publish
rollback
```

---

# 10.6 节点级状态

```text
PENDING
RUNNING
SUCCESS
FAILED
SKIPPED
PAUSED
CANCELLED
RETRYING
```

---

# 11. 功能八：复盘研究

# 11.1 复盘对象

```text
日复盘
周复盘
月复盘
策略复盘
组合复盘
股票复盘
交易复盘
因子复盘
AI复盘
```

---

# 11.2 每日复盘

自动生成：

```text
市场环境
指数表现
行业表现
风格表现
强势股
弱势股
涨停
跌停
成交量
波动率
市场情绪
资金流
新闻事件
策略表现
模拟交易表现
持仓表现
```

---

# 11.3 单笔交易复盘

```text
为什么买
买入时知道什么
买入时不知道什么
因子分数
AI理由
市场状态
当时风险
随后发生什么
为什么卖
卖出后发生什么
是否卖飞
是否应止损
是否存在数据问题
```

---

# 11.4 AI 复盘输出

```text
事实
 ↓
归因
 ↓
问题
 ↓
反事实分析
 ↓
改进建议
 ↓
Skill 更新建议
```

---

# 11.5 反事实分析

必须支持：

```text
如果止损 -5% 会怎样？
如果止损 -8% 会怎样？
如果持有 5 天呢？
如果不卖飞呢？
如果选择 Top20 而不是 Top10？
如果去掉某因子？
```

用于寻找策略敏感性。

---

# 12. 功能九：持仓研究

# 12.1 Portfolio Research

目标：

不是简单显示持仓，而是回答：

```text
我现在持有什么？
为什么持有？
哪些风险最大？
哪些因子驱动收益？
行业是否集中？
是否存在相关性风险？
哪些股票正在偏离原假设？
```

---

# 12.2 Portfolio Risk

至少：

```text
单票权重
行业权重
主题权重
因子暴露
Beta
波动率
相关性
集中度
最大单票风险
最大行业风险
流动性风险
事件风险
```

---

# 12.3 持仓 Thesis

每个持仓必须保存：

```text
thesis
entry_reason
expected_catalyst
expected_holding_period
invalid_conditions
take_profit_rule
stop_loss_rule
```

AI 每次更新时回答：

```text
原始投资逻辑仍成立吗？
哪些事实支持？
哪些事实反驳？
是否需要退出？
```

---

# 13. AI Agent 架构扩展

现有 Agent：

```text
Market Analyst
Social Analyst
News Analyst
Fundamentals Analyst
Bull Researcher
Bear Researcher
Research Manager
Trader
Risky Analyst
Safe Analyst
Neutral Analyst
Risk Judge
```

新增：

```text
Factor Researcher
Factor Validator
Strategy Researcher
Backtest Analyst
Screening Analyst
Simulation Analyst
Monitoring Analyst
Postmortem Analyst
Portfolio Analyst
Learning Analyst
Workflow Planner
Skill Evaluator
```

---

# 14. AI 分析链统一协议

每个 Agent 输出必须包含：

```json
{
  "agent_id": "...",
  "task_id": "...",
  "analysis_id": "...",
  "facts": [],
  "signals": [],
  "hypotheses": [],
  "evidence": [],
  "risks": [],
  "recommendations": [],
  "confidence": 0.0,
  "data_cutoff": "...",
  "available_time_cutoff": "...",
  "skill_id": "...",
  "skill_version": "..."
}
```

---

# 15. 数据证据链

AI 不能只给：

```text
“我认为这只股票不错”
```

必须能追溯：

```text
结论
 ↓
Rule / Factor / Skill
 ↓
Input Dataset
 ↓
Data Timestamp
 ↓
Calculation
 ↓
Output
```

必须提供：

```text
evidence_id
source
available_time
factor_id
formula_version
dataset_version
```

---

# 16. API 规范

新增 Router：

```text
app/routers/factors.py
app/routers/strategies.py
app/routers/backtests.py
app/routers/simulations.py
app/routers/monitoring.py
app/routers/alerts.py
app/routers/skills.py
app/routers/workflows.py
app/routers/research.py
app/routers/portfolio_research.py
app/routers/learning.py
```

---

# 16.1 Factor API

```http
GET    /factors
GET    /factors/{factor_id}
POST   /factors
PUT    /factors/{factor_id}
POST   /factors/compute
POST   /factors/analyze
GET    /factors/{factor_id}/performance
GET    /factors/{factor_id}/exposure
```

---

# 16.2 Strategy API

```http
GET    /strategies
POST   /strategies
GET    /strategies/{id}
PUT    /strategies/{id}
POST   /strategies/{id}/validate
POST   /strategies/{id}/backtest
POST   /strategies/{id}/simulate
POST   /strategies/{id}/clone
POST   /strategies/{id}/publish
```

---

# 16.3 Backtest API

```http
POST /backtests
GET  /backtests/{id}
POST /backtests/{id}/cancel
GET  /backtests/{id}/trades
GET  /backtests/{id}/equity
GET  /backtests/{id}/metrics
GET  /backtests/{id}/attribution
```

---

# 16.4 Simulation API

```http
POST /simulations
GET  /simulations
GET  /simulations/{id}
POST /simulations/{id}/start
POST /simulations/{id}/pause
POST /simulations/{id}/resume
POST /simulations/{id}/close
GET  /simulations/{id}/positions
GET  /simulations/{id}/trades
GET  /simulations/{id}/performance
GET  /simulations/{id}/postmortem
```

---

# 16.5 Monitoring API

```http
GET  /monitors
POST /monitors
PUT  /monitors/{id}
POST /monitors/{id}/enable
POST /monitors/{id}/disable
GET  /alerts
POST /alerts/{id}/ack
```

---

# 16.6 Skill API

```http
GET    /skills
POST   /skills
GET    /skills/{id}
PUT    /skills/{id}
POST   /skills/{id}/validate
POST   /skills/{id}/evaluate
POST   /skills/{id}/publish
POST   /skills/{id}/rollback
```

---

# 16.7 Workflow API

```http
POST /workflows
GET  /workflows
GET  /workflows/{id}
PUT  /workflows/{id}
POST /workflows/{id}/validate
POST /workflows/{id}/run
POST /workflows/{id}/pause
POST /workflows/{id}/resume
POST /workflows/{id}/cancel
GET  /workflows/{id}/runs
```

---

# 17. 数据模型

建议 MongoDB Collections：

```text
factor_definitions
factor_runs
factor_values
factor_analysis_results
factor_combinations

strategies
strategy_versions
strategy_runs

backtests
backtest_orders
backtest_fills
backtest_positions
backtest_equity
backtest_metrics

simulations
simulation_positions
simulation_orders
simulation_fills
simulation_events
simulation_outcomes
simulation_attributions

monitor_rules
monitor_events
alerts

skills
skill_versions
skill_runs
skill_evaluations

workflows
workflow_versions
workflow_runs
workflow_node_runs

research_reports
research_runs
postmortems
learning_lessons
learning_candidates

portfolios
portfolio_positions
portfolio_snapshots
portfolio_risk_snapshots
portfolio_research
```

---

# 18. Redis 使用规范

当前项目已使用 Redis 做队列、缓存、实时进度。新增功能必须统一命名。

```text
factor:job:{id}
factor:progress:{id}

backtest:job:{id}
backtest:progress:{id}

simulation:{id}
simulation:events:{id}

monitor:event:{id}
alert:{id}

workflow:run:{id}
workflow:events:{id}

portfolio:snapshot:{portfolio_id}
```

必须设置 TTL。

---

# 19. Worker 架构

目前项目已有 Queue/Worker 能力。新增任务全部异步化：

```text
factor_compute
factor_analysis
strategy_screen
backtest_run
simulation_tick
monitor_tick
workflow_run
research_run
postmortem_run
learning_run
```

不要在 HTTP 请求中直接执行长时间计算。

---

# 20. 任务状态统一

所有异步任务统一：

```text
CREATED
QUEUED
RUNNING
PAUSED
SUCCEEDED
FAILED
CANCELLED
EXPIRED
```

每个任务保存：

```text
progress
current_step
total_steps
message
started_at
finished_at
error_code
error_message
```

---

# 21. 前端页面

必须新增：

```text
Factor Lab
Strategy Lab
Backtest Lab
Simulation Lab
Monitoring Center
AI Skill Center
Workflow Designer
Research Center
Portfolio Research
Learning Center
```

---

# 22. Factor Lab 页面

必须有：

```text
因子列表
分类
搜索
预览
公式
依赖
参数
计算
因子IC
分层收益
相关性矩阵
因子组合
因子稳定性
```

---

# 23. Strategy Lab

必须支持：

```text
策略列表
策略版本
规则编辑器
因子选择
参数
股票池
交易规则
风险规则
一键回测
一键模拟
策略比较
参数敏感性
```

---

# 24. Backtest Lab

页面：

```text
配置
运行状态
净值曲线
回撤
交易点
分年度收益
行业归因
因子归因
交易列表
费用分析
参数敏感性
```

---

# 25. Simulation Lab

显示：

```text
模拟资金
净值
持仓
开仓原因
止盈
止损
浮盈浮亏
已实现收益
卖飞
亏损归因
AI复盘
```

---

# 26. Monitoring Center

显示：

```text
监控对象
规则
实时状态
触发事件
告警
告警确认
历史记录
```

---

# 27. Skill Center

必须：

```text
Skill 列表
分类
版本
启用
停用
调试
输入测试
输出验证
评测
版本对比
```

---

# 28. Workflow Designer

推荐 Vue Flow / 类似 DAG 编辑组件。

左侧：

```text
数据
因子
策略
AI
回测
模拟
监控
研究
控制
```

中心：

```text
Canvas
```

右侧：

```text
节点配置
输入
输出
参数
权限
超时
重试
```

底部：

```text
Validate
Debug
Run
Save Version
Publish
```

---

# 29. Research Center

提供：

```text
日复盘
周复盘
月复盘
股票复盘
策略复盘
因子复盘
AI研究
自定义研究
```

---

# 30. Portfolio Research

提供：

```text
持仓总览
组合风险
因子暴露
行业暴露
相关性
股票 Thesis
风险事件
AI 研究
建议
复盘
```

---

# 31. AI 学习中心

必须提供：

```text
错误案例
卖飞案例
成功案例
策略失败
因子失效
模型误判
数据错误
```

每条形成：

```text
Case
 → Attribution
 → Lesson
 → Candidate Improvement
 → Evaluation
```

---

# 32. 反事实分析系统

统一对象：

```python
CounterfactualScenario:
    base_run_id
    changed_parameter
    old_value
    new_value
    result_diff
```

必须支持：

```text
止损变化
止盈变化
持仓期限
选股数量
因子权重
股票池
再平衡周期
手续费
滑点
模型
Skill
```

---

# 33. 策略实验系统

所有新策略不得覆盖旧策略。

采用：

```text
Strategy ID
 ├── v1
 ├── v2
 ├── v3
 └── candidate
```

实验结果保存：

```text
dataset_version
factor_version
strategy_version
skill_version
model_version
code_commit
```

最终可以做到结果复现。

---

# 34. AI 自动优化规则

AI 可以：

```text
提出
比较
模拟
评估
生成新版本
```

默认不能：

```text
直接生产发布
```

发布必须：

```text
AI Candidate
 ↓
Backtest
 ↓
Out-of-Sample Test
 ↓
Stress Test
 ↓
Human Approval
 ↓
Publish
```

---

# 35. 防止过拟合

所有策略必须至少：

```text
Train
Validation
Test
Out-of-Sample
```

高级功能：

```text
Walk Forward
Rolling Window
Monte Carlo
Parameter Perturbation
Transaction Cost Stress
Slippage Stress
Market Regime Test
```

---

# 36. 市场环境分类

新增：

```text
Bull
Bear
Sideways
High Volatility
Low Volatility
Risk-On
Risk-Off
```

通过规则/AI识别。

策略绩效必须按 Regime 分解。

---

# 37. 因子与策略关系图

新增 Factor Exposure：

```text
Strategy
  ↓
Holdings
  ↓
Factor Exposure
```

回答：

```text
该策略到底是在赚什么？
```

例如：

```text
Momentum +0.61
Value    +0.18
Quality  +0.42
Volatility -0.23
```

---

# 38. 组合策略

支持：

```text
多策略
多账户
多市场
统一资金池
```

组合层：

```text
Strategy A 40%
Strategy B 30%
Strategy C 30%
```

并支持：

```text
风险预算
最大相关性
最大行业暴露
最大单股暴露
```

---

# 39. 实时策略触发

策略必须提供：

```python
evaluate_realtime(market_context)
```

而不是重新运行完整回测。

输出：

```json
{
  "signal": "BUY",
  "security_id": "...",
  "score": 0.91,
  "reasons": [],
  "risk": [],
  "timestamp": "..."
}
```

---

# 40. AI 工作流和现有 LangGraph 的关系

不要让 Workflow Designer 取代 TradingAgents Graph。

两者层级：

```text
Workflow Layer
     ↓
业务编排
     ↓
AI Agent Runtime
     ↓
LangGraph
     ↓
Agent Nodes
```

Workflow 负责：

```text
什么时候运行什么
```

LangGraph 负责：

```text
AI Agent 内部如何思考/协作
```

---

# 41. Skill 和 Agent 的关系

```text
Workflow
  ↓
Skill
  ↓
Agent
  ↓
Tools
  ↓
Data
```

一个 Skill 可以：

```text
调用多个 Agent
```

一个 Agent 可以：

```text
执行多个 Skill
```

不得一对一绑定。

---

# 42. Monitoring 和 Simulation 的关系

模拟运行产生事件：

```text
ENTRY
EXIT
STOP_LOSS
TAKE_PROFIT
TRAILING_STOP
SIGNAL_CHANGE
```

Monitoring 监听这些事件。

不要复制一套告警系统。

---

# 43. 失败处理

所有引擎必须：

```text
任务级失败
节点级失败
因子级失败
股票级失败
数据源级失败
```

例如 120 因子计算时：

```text
Factor 38 failed
```

不应该导致：

```text
Factor 1~37
39~120
```

全部失败。

但如果：

```text
核心行情数据缺失
```

则任务必须终止。

---

# 44. 数据源回退

现有项目已经具备多数据源思路。

新增统一：

```text
Primary
Fallback
Fallback2
```

数据源失败必须记录：

```text
provider
error
timestamp
retry_count
```

数据源切换不能悄悄发生而不留痕迹。

---

# 45. 性能目标

首期目标：

```text
120+ 因子
5000 股票
5 年日线
```

批量计算。

要求：

```text
因子依赖复用
分区读取
列式存储
缓存
并行
增量计算
```

不得：

```text
每个股票单独发网络请求
```

---

# 46. 因子缓存

Key：

```text
factor:{factor_id}:{version}:{market}:{date}:{universe_hash}
```

保存：

```text
status
dataset_version
calculation_version
created_at
```

---

# 47. 回测缓存

相同：

```text
strategy_version
dataset_version
factor_version
backtest_config
```

生成 deterministic hash。

相同配置直接复用。

---

# 48. 安全

AI Skill 必须限制：

```text
工具权限
数据权限
组合权限
工作流权限
策略发布权限
```

禁止 Skill 自行获取：

```text
管理员配置
数据库密码
API Key
其他用户数据
```

---

# 49. 审计日志

所有以下动作必须记录：

```text
创建策略
修改策略
运行回测
运行模拟
创建预警
修改 Skill
发布 Skill
发布策略
修改工作流
启用监控
暂停监控
AI 生成改进方案
人工批准
```

---

# 50. 测试策略

## 50.1 单元测试

必须覆盖：

```text
每个 Factor
每个 Operator
每个 Strategy Rule
每个 Risk Rule
每个 Stop Rule
每个 Metric
每个 Skill validator
Workflow validator
```

---

## 50.2 数据测试

包括：

```text
停牌
涨跌停
缺失
重复
未来日期
复权
除权
财务数据发布日期
新闻发布日期
```

---

## 50.3 回测一致性测试

要求：

```text
同数据
同策略
同参数
```

多次运行：

```text
结果完全一致
```

---

## 50.4 Property-based Tests

例如：

```text
加入手续费后收益不能变高
增加滑点不能提高收益
提高止损不能保证收益增加
```

---

# 51. AI 输出评测

Skill/Agent 必须有：

```text
事实准确性
数据引用完整性
结构化输出正确率
幻觉率
决策一致性
重跑稳定性
```

---

# 52. 回测质量等级

输出：

```text
A：严格可复现
B：存在有限近似
C：存在数据缺失
D：不可用于研究
```

如果存在：

```text
未来函数
```

直接：

```text
INVALID
```

---

# 53. 实现顺序

不要按用户提出的 1→9 机械开发。

正确顺序：

### Phase 0：基础设施

```text
统一时间语义
数据模型
任务模型
版本体系
事件模型
权限模型
```

### Phase 1：Factor Engine

```text
Factor Registry
120 factors
parallel executor
normalization
neutralization
factor analysis
```

### Phase 2：Strategy Engine

```text
Strategy DSL
策略库
参数化
因子组合
股票池
```

### Phase 3：Backtest Engine

```text
event-driven
execution
portfolio
metrics
attribution
```

### Phase 4：Simulation

```text
selection snapshot
virtual orders
stop loss
take profit
simulation events
```

### Phase 5：Monitoring

```text
realtime
rule engine
alerts
```

### Phase 6：AI Skill

```text
registry
manifest
tools
validators
evaluators
```

### Phase 7：AI Workflow

```text
node schema
DAG
runtime
designer
```

### Phase 8：Research

```text
postmortem
portfolio research
daily/weekly/monthly review
counterfactual
```

### Phase 9：Learning

```text
case bank
memory
skill improvement
strategy candidate
evaluation
approval
```

---

# 54. Phase 0 的具体任务

## 任务 P0-01：建立统一时间协议

新增：

```text
tradingagents/core/time/
```

实现：

```python
TradingTimestamp
DataAvailabilityPolicy
```

验收：

- 所有新数据对象都有 available_time
- 回测拒绝未来数据
- 财务数据使用披露时间，不使用财报周期结束时间作为可用时间

---

## P0-02：统一 Event

新增：

```text
tradingagents/core/events.py
```

事件：

```text
MarketEvent
SignalEvent
OrderEvent
FillEvent
PositionEvent
AlertEvent
ResearchEvent
LearningEvent
```

---

## P0-03：统一 Task

新增：

```text
TaskContext
TaskResult
TaskStatus
```

让 Factor/Backtest/Simulation/Workflow 共用任务生命周期。

---

# 55. Phase 1 具体任务

## F-001 Factor Registry

必须：

```text
register()
get()
list()
enable()
disable()
version()
dependencies()
```

## F-002 Factor Executor

必须：

```text
DAG
parallel
cache
failure isolation
progress
```

## F-003 Factor Analyzer

必须：

```text
IC
RankIC
group return
decay
exposure
```

## F-004 Factor UI

完成：

```text
列表
详情
计算
分析
组合
```

验收：

> 选择任意 20 个因子，指定股票池和日期范围，可一次提交并行计算，并产生完整因子分析报告。

---

# 56. Phase 2 具体任务

## S-001 Strategy DSL

实现：

```text
Parser
Validator
Evaluator
Compiler
```

## S-002 Strategy Registry

实现版本管理。

## S-003 Strategy Runner

输入：

```text
Universe
Factors
Market
Strategy
```

输出：

```text
Candidates
Signals
Weights
```

验收：

> 用户不写 Python，只通过策略编辑器配置规则即可运行选股。

---

# 57. Phase 3 具体任务

## B-001 Backtest Event Engine

实现：

```text
event loop
order book abstraction
execution simulator
portfolio
```

## B-002 Cost Model

至少：

```text
commission
tax
slippage
impact
```

## B-003 Corporate Actions

支持：

```text
split
bonus
dividend
rights
```

验收：

> 任意已发布策略都可从 Strategy Lab 一键进入 Backtest Lab。

---

# 58. Phase 4 具体任务

## SIM-001 Selection Snapshot

选股结果不可修改。

## SIM-002 Simulation Engine

按照历史真实行情推进。

## SIM-003 Exit Rules

支持：

```text
TP
SL
Trailing
TimeExit
SignalExit
```

## SIM-004 Postmortem

自动：

```text
profit attribution
loss attribution
sell-too-early attribution
```

验收：

> 每一笔模拟交易都有完整可追溯生命周期。

---

# 59. Phase 5 具体任务

实现：

```text
MarketMonitor
StrategyMonitor
PortfolioMonitor
FactorMonitor
AlertEngine
```

支持：

```text
实时事件
规则
去重
冷却
通知
```

---

# 60. Phase 6 具体任务

实现 Skill：

```text
FactorResearchSkill
StrategyResearchSkill
BacktestAnalysisSkill
StockScreeningSkill
SimulationPostmortemSkill
PortfolioResearchSkill
DailyReviewSkill
```

---

# 61. Phase 7 具体任务

实现 Workflow：

```text
Node Registry
Workflow Schema
Validator
Compiler
Runtime
Event Bus
Version
```

然后前端可视化。

---

# 62. Phase 8 具体任务

实现：

```text
ResearchReport
ResearchRun
Postmortem
Counterfactual
```

---

# 63. Phase 9 具体任务

实现：

```text
Lesson
Case
LearningCandidate
SkillImprovement
StrategyCandidate
```

所有自动优化必须：

```text
候选
→ 回测
→ OOS
→ 压力测试
→ 人工批准
```

---

# 64. Definition of Done

任何一项功能只有同时满足以下条件才算完成：

```text
[ ] 数据模型完成
[ ] 服务层完成
[ ] API完成
[ ] 异步任务完成
[ ] Redis事件完成
[ ] 前端页面完成
[ ] 权限完成
[ ] 审计完成
[ ] 单元测试完成
[ ] 集成测试完成
[ ] 错误处理完成
[ ] 日志完成
[ ] 指标监控完成
[ ] 文档完成
[ ] 版本化完成
[ ] 回滚方案完成
```

---

# 65. 不允许出现的实现方式

## 禁止 1：把 120 个因子分别写成 120 个独立任务

必须使用：

```text
Factor Registry + Dependency DAG + Vectorized Executor
```

## 禁止 2：回测直接遍历 DataFrame 进行 if/else 模拟

必须有：

```text
Event → Signal → Order → Fill → Position
```

## 禁止 3：AI 自动修改生产策略

必须：

```text
Candidate → Test → Approval → Publish
```

## 禁止 4：Skill 只是一个 Prompt

必须具备：

```text
tools + schema + permissions + evaluator + version
```

## 禁止 5：Workflow 直接复制 LangGraph

Workflow 是业务编排层。

## 禁止 6：重复实现通知系统

统一进入 AlertEngine。

## 禁止 7：不同模块各自计算收益率

所有 PnL 统一经过 Portfolio/PnL Engine。

---

# 66. 最终验收场景

必须实现以下完整演示：

## 场景 A：AI 多因子选股

```text
用户选择：
A股
沪深300
120因子
多因子策略
Top20
AI基本面Skill
AI风险Skill
```

系统：

```text
计算因子
→ 组合
→ 排名
→ Top20
→ AI分析
→ Top10
```

---

## 场景 B：自动模拟

```text
Top10
↓
虚拟资金100000
↓
按评分分配仓位
↓
止损8%
止盈20%
移动止盈10%
最大持仓20天
```

每天自动推进。

---

## 场景 C：自动复盘

出现：

```text
亏损
```

AI 自动判断：

```text
因子正确/错误
行业错误
市场环境错误
止损正确/错误
数据是否有问题
```

---

## 场景 D：卖飞分析

```text
卖出后20天继续上涨32%
```

系统：

```text
标记 SELL_TOO_EARLY
↓
分析：
RSI是否过热？
趋势是否仍成立？
因子是否仍强？
市场是否继续 Risk-On？
```

然后给出：

```text
卖飞原因
改进建议
```

---

## 场景 E：策略学习

AI 发现：

```text
止盈20%频繁卖飞
```

生成候选：

```text
TP20 → TP30
```

然后：

```text
Backtest
→ OOS
→ Stress
```

如果通过：

```text
生成 Strategy v2
```

但不自动生产发布。

---

# 67. 最终系统能力矩阵

| 能力 | 人工 | 规则 | AI | 自动化 |
|---|---:|---:|---:|---:|
| 因子计算 | ✓ | ✓ | | ✓ |
| 因子研究 | ✓ | ✓ | ✓ | ✓ |
| 选股 | ✓ | ✓ | ✓ | ✓ |
| 策略 | ✓ | ✓ | ✓ | ✓ |
| 回测 | ✓ | ✓ | | ✓ |
| 模拟 | ✓ | ✓ | ✓ | ✓ |
| 监控 | ✓ | ✓ | | ✓ |
| 预警 | ✓ | ✓ | ✓ | ✓ |
| Skill | ✓ | | ✓ | ✓ |
| Workflow | ✓ | ✓ | ✓ | ✓ |
| 复盘 | ✓ | ✓ | ✓ | ✓ |
| 持仓研究 | ✓ | ✓ | ✓ | ✓ |
| 学习 | ✓ | ✓ | ✓ | 半自动 |

---

# 68. 开发 AI Agent 的执行协议

后续任何 AI 编码 Agent 接到需求，必须先回答：

```text
1. 该需求属于哪个 Domain？
2. 是否需要新增数据模型？
3. 是否需要新的 Task？
4. 是否需要新的 Event？
5. 是否需要 Router？
6. 是否需要 Service？
7. 是否需要 Worker？
8. 是否需要 Redis Key？
9. 是否需要前端页面？
10. 是否需要 Skill？
11. 是否需要修改 AgentState？
12. 是否需要修改 LangGraph？
13. 是否会影响回测的一致性？
14. 是否会产生未来函数？
15. 是否需要版本化？
16. 是否需要审计日志？
17. 如何测试？
18. 如何回滚？
```

任何回答不完整，不得开始编码。

---

# 69. 开发完成后的最终系统

最终目标结构：

```text
TradingAgents-CN
│
├── Core Platform
│
├── Data Platform
│   ├── Market Data
│   ├── Fundamental Data
│   ├── News
│   └── Alternative Data
│
├── Factor Platform
│   ├── 120+ Factors
│   ├── DAG
│   ├── Factor Lab
│   └── Factor Research
│
├── Strategy Platform
│   ├── Strategy DSL
│   ├── Strategy Registry
│   ├── Strategy Lab
│   └── Strategy Marketplace
│
├── Backtest Platform
│   ├── Event Engine
│   ├── Portfolio Engine
│   ├── Cost Model
│   └── Attribution
│
├── Simulation Platform
│   ├── Auto Screening
│   ├── Virtual Trading
│   ├── TP/SL
│   └── Postmortem
│
├── Monitoring Platform
│   ├── Realtime
│   ├── Rules
│   └── Alerts
│
├── AI Platform
│   ├── Agents
│   ├── Skills
│   ├── Memory
│   └── Evaluation
│
├── Workflow Platform
│   ├── Designer
│   ├── Runtime
│   └── Scheduler
│
├── Research Platform
│   ├── Review
│   ├── Postmortem
│   ├── Counterfactual
│   └── Portfolio Research
│
└── Learning Platform
    ├── Cases
    ├── Lessons
    ├── Candidate Improvements
    └── Strategy / Skill Evolution
```

---

# 70. 最关键的工程结论

这个项目后续不要继续采用“增加一个功能就往 `AnalysisService`、`TradingAgentsGraph`、Router 里面堆代码”的方式。

必须正式进入：

```text
Domain-Driven Modules
+
Event Driven
+
Versioned Research
+
Deterministic Backtesting
+
AI Skill Runtime
+
Workflow Runtime
+
Human-in-the-loop Learning
```

最终把系统从：

```text
AI 股票分析工具
```

升级成：

```text
AI Quant Research & Strategy Experiment Platform
```

但仍然保留现在 TradingAgents-CN 最核心的 LangGraph 多智能体能力，作为 AI Research Runtime，而不是推倒重写。

---

# 71. 本文与当前源码的对应关系

当前源码中的关键入口：

```text
tradingagents/graph/trading_graph.py
    → LLM / Graph / Runtime 装配

tradingagents/graph/setup.py
    → LangGraph 工作流拓扑

tradingagents/graph/conditional_logic.py
    → Agent 循环 / Debate / Tool Call 控制

tradingagents/agents/utils/agent_states.py
    → AgentState / DebateState

tradingagents/graph/propagation.py
    → 初始状态 / Graph execution config

tradingagents/graph/reflection.py
    → Memory / Reflection

tradingagents/graph/signal_processing.py
    → 非结构化决策 → 结构化决策

app/services/analysis_service.py
    → Web 层 → TradingAgents 引擎

app/routers/analysis.py
    → 现有分析 API
```

新增模块应围绕这些入口扩展，而不是修改它们的职责边界。

---

# 72. 第一阶段开发完成判定

第一阶段真正完成，不是“页面能看到”。

必须做到：

```text
120+ 因子
+
因子组合
+
策略 DSL
+
至少 20 个内置策略
+
事件驱动回测
+
自动模拟
+
止盈止损
+
卖飞识别
+
亏损归因
+
基础 Monitoring
+
基础 Alert
+
Skill Runtime
+
基础 Workflow Runtime
+
复盘
+
持仓研究
```

并且最核心的闭环必须可以完整跑通：

```text
数据
→ 因子
→ 策略
→ 选股
→ AI
→ 回测
→ 自动模拟
→ 监控
→ 卖出/止盈/止损
→ 复盘
→ 归因
→ 学习
→ 候选策略 v2
→ 再回测
```

只有这个闭环打通，才算真正完成《股票分析/选股》功能体系，而不是完成若干互相孤立的页面。
