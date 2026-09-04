export type AlertMarket = 'CN' | 'HK' | 'US' | 'SYSTEM'
export type AlertSeverity = 'info' | 'warning' | 'critical'
export type AlertEvaluationMode = 'edge' | 'level' | 'once'
export type AlertQualityStatus = 'valid' | 'partial' | 'stale' | 'missing' | 'error'
export type AlertConditionState = 'true' | 'false' | 'unknown'
export type AlertEventKind = 'triggered' | 'recovered' | 'rule_health'
export type AlertChannel = 'in_app' | 'websocket'
export type AlertCompareOperator = 'gt' | 'gte' | 'lt' | 'lte' | 'eq' | 'neq' | 'between'

export type AlertType =
  | 'price_above'
  | 'price_below'
  | 'pct_change_above'
  | 'pct_change_below'
  | 'gap_up'
  | 'gap_down'
  | 'factor_above'
  | 'factor_below'
  | 'factor_between'
  | 'factor_cross_up'
  | 'factor_cross_down'
  | 'factor_rank_enter'
  | 'factor_rank_exit'
  | 'composite_score_above'
  | 'composite_score_below'
  | 'new_high'
  | 'new_low'
  | 'volume_ratio_above'
  | 'amount_above'
  | 'turnover_above'
  | 'liquidity_below'
  | 'no_quote'
  | 'stale_quote'
  | 'limit_up'
  | 'limit_down'
  | 'data_quality_changed'
  | 'negative_news_detected'
  | 'positive_news_detected'
  | 'news_volume_spike'
  | 'sentiment_cross_threshold'
  | 'high_severity_event'
  | 'stop_loss_near'
  | 'stop_loss_triggered'
  | 'take_profit_near'
  | 'take_profit_triggered'
  | 'trailing_stop_triggered'
  | 'position_drawdown'
  | 'account_drawdown'
  | 'position_weight_exceeded'
  | 'industry_weight_exceeded'
  | 'cash_below'
  | 'datasource_down'
  | 'datasource_latency'
  | 'factor_job_failed'
  | 'scheduler_job_failed'
  | 'worker_heartbeat_lost'
  | 'notification_delivery_failed'

export interface SymbolAlertScope {
  scope_type: 'symbol'
  symbol: string
}

export interface WatchlistAlertScope {
  scope_type: 'watchlist'
  watchlist_id?: string | null
  symbols: string[]
}

export interface StrategyUniverseAlertScope {
  scope_type: 'strategy_universe'
  strategy_version_id: string
}

export interface PaperPositionAlertScope {
  scope_type: 'paper_position'
  account_id: string
}

export interface PaperAccountAlertScope {
  scope_type: 'paper_account'
  account_id: string
}

export type AlertScope =
  | SymbolAlertScope
  | WatchlistAlertScope
  | StrategyUniverseAlertScope
  | PaperPositionAlertScope
  | PaperAccountAlertScope

export interface CurrentValueOperand { kind: 'current_value' }
export interface PreviousValueOperand { kind: 'previous_value' }
export interface ConstantOperand { kind: 'constant'; value: string }
export interface ChangeRateOperand { kind: 'change_rate'; window_seconds: number }
export interface FactorOperand {
  kind: 'factor'
  factor_id: string
  version: number
  lag: number
}

export type AlertOperand =
  | CurrentValueOperand
  | PreviousValueOperand
  | ConstantOperand
  | ChangeRateOperand
  | FactorOperand

export interface CompareAlertCondition {
  type: 'compare'
  left: AlertOperand
  operator: AlertCompareOperator
  right: AlertOperand
  upper?: AlertOperand | null
}

export interface CrossAlertCondition {
  type: 'cross_up' | 'cross_down'
  left: AlertOperand
  right: AlertOperand
}

export interface AllAlertCondition {
  type: 'all'
  children: AlertCondition[]
}

export interface AnyAlertCondition {
  type: 'any'
  children: AlertCondition[]
}

export interface NotAlertCondition {
  type: 'not'
  child: AlertCondition
}

export type AlertCondition =
  | CompareAlertCondition
  | CrossAlertCondition
  | AllAlertCondition
  | AnyAlertCondition
  | NotAlertCondition

export interface AlertRuleStateSummary {
  evaluated_scope_count: number
  triggered_scope_count: number
  last_evaluated_at: string | null
}

export interface AlertRule {
  rule_id: string
  user_id: string
  name: string
  description: string
  enabled: boolean
  alert_type: AlertType
  scope: AlertScope
  market: AlertMarket
  trigger: {
    condition: AlertCondition
    for_seconds?: number | null
    for_evaluations?: number | null
  }
  evaluation_mode: AlertEvaluationMode
  frequency_seconds: number
  active_schedule:
    | { schedule_type: 'market_hours' }
    | { schedule_type: 'all_day' }
    | {
        schedule_type: 'custom'
        timezone_name: string
        weekdays: number[]
        start_time: string
        end_time: string
      }
  cooldown_seconds: number
  recovery_enabled: boolean
  severity: AlertSeverity
  channels: AlertChannel[]
  action: 'notify_only' | 'paper_trade'
  origin: 'user' | 'automation' | 'system'
  automation_id: string | null
  paper_account_id: string | null
  lookback_window: number | null
  event_categories: string[]
  max_events_per_day: number
  expires_at: string | null
  state: AlertRuleStateSummary
  version: number
  condition_version: number
  created_at: string
  updated_at: string
}

export interface AlertRuleState {
  rule_id: string
  user_id: string
  scope_key: string
  symbol: string | null
  last_value: string | boolean | null
  last_condition_state: AlertConditionState
  last_determined_state: 'true' | 'false' | null
  last_evaluated_at: string | null
  last_triggered_at: string | null
  cooldown_until: string | null
  events_today: number
  active_event_open: boolean
  state_revision: number
  updated_at: string
}

export interface AlertEvent {
  event_id: string
  rule_id: string
  rule_version: number
  condition_version: number
  user_id: string
  scope_key: string
  symbol: string | null
  kind: AlertEventKind
  severity: AlertSeverity
  direction: string
  condition_state: AlertConditionState
  current_value: string | boolean | null
  previous_value: string | boolean | null
  quote_time: string
  ingested_at: string
  evaluated_at: string
  source: string
  latency_seconds: string
  quality_status: AlertQualityStatus
  stale: boolean
  actual_symbol_count: number
  actual_symbols_checksum: string | null
  universe_snapshot_id: string | null
  fingerprint: string
  acknowledged_at: string | null
  created_at: string
}

export interface AlertRuleDetail {
  rule: AlertRule
  states: AlertRuleState[]
  recent_events: AlertEvent[]
}

export interface AlertPage<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export interface AlertValidationIssue {
  code: string
  message: string
  path: string | null
}

export interface AlertValidationResult {
  valid: boolean
  rule: AlertRule | null
  errors: AlertValidationIssue[]
  warnings: AlertValidationIssue[]
  error_code: string | null
}

export interface AlertPreviewItem {
  symbol: string | null
  condition_state: AlertConditionState
  value: string | boolean | null
  quote_time: string
  ingested_at: string
  evaluated_at: string
  source: string
  quality_status: AlertQualityStatus
}

export interface AlertPreviewResult {
  rule_id: string
  evaluated_at: string
  universe_snapshot_id: string | null
  symbols_checksum: string
  results: AlertPreviewItem[]
  state_persisted: false
  notification_sent: false
}

export interface AlertHealth {
  status: 'healthy' | 'degraded'
  checked_at: string
  owner: {
    enabled_rule_count: number
    recent_event_count: number
  }
  evaluation_batches: {
    recent_count: number
    failure_count: number
    last_status: string | null
    last_completed_at: string | null
  }
  latency_seconds: {
    sample_count: number
    average: number | null
    maximum: number | null
  }
  data_sources: {
    market_quotes: {
      available: boolean
      source: string | null
      last_ingested_at: string | null
    }
  }
}

export interface AlertRuleDraft {
  rule_id?: string
  name: string
  description: string
  enabled: boolean
  alert_type: AlertType
  market: Exclude<AlertMarket, 'SYSTEM'>
  scope: AlertScope
  left_kind: 'current_value' | 'change_rate' | 'factor'
  operator: AlertCompareOperator | 'cross_up' | 'cross_down'
  threshold: string
  upper_threshold: string
  change_window_seconds: number
  factor_id: string
  factor_version: number
  factor_lag: number
  evaluation_mode: AlertEvaluationMode
  frequency_seconds: number
  duration_mode: 'none' | 'seconds' | 'evaluations'
  duration_value: number
  schedule_type: 'market_hours' | 'all_day'
  cooldown_seconds: number
  recovery_enabled: boolean
  severity: AlertSeverity
  channels: AlertChannel[]
  max_events_per_day: number
  version?: number
}
