import type {
  AlertCondition,
  AlertEvent,
  AlertMarket,
  AlertQualityStatus,
  AlertRule,
  AlertRuleDraft,
  AlertSeverity,
  AlertType
} from '@/types/alert'

export const alertTypeOptions: Array<{
  value: AlertType
  label: string
  description: string
  leftKind: AlertRuleDraft['left_kind']
  operator: AlertRuleDraft['operator']
}> = [
  { value: 'price_above', label: '价格高于', description: '最新价格高于设定值', leftKind: 'current_value', operator: 'gt' },
  { value: 'price_below', label: '价格低于', description: '最新价格低于设定值', leftKind: 'current_value', operator: 'lt' },
  { value: 'pct_change_above', label: '涨幅超过', description: '指定窗口涨幅超过阈值', leftKind: 'change_rate', operator: 'gt' },
  { value: 'pct_change_below', label: '跌幅超过', description: '指定窗口变化率低于阈值', leftKind: 'change_rate', operator: 'lt' },
  { value: 'factor_above', label: '因子高于', description: '已发布因子值高于阈值', leftKind: 'factor', operator: 'gt' },
  { value: 'factor_below', label: '因子低于', description: '已发布因子值低于阈值', leftKind: 'factor', operator: 'lt' },
  { value: 'factor_between', label: '因子区间', description: '因子值进入指定区间', leftKind: 'factor', operator: 'between' },
  { value: 'factor_cross_up', label: '因子上穿', description: '因子从阈值下方向上穿越', leftKind: 'factor', operator: 'cross_up' },
  { value: 'factor_cross_down', label: '因子下穿', description: '因子从阈值上方向下穿越', leftKind: 'factor', operator: 'cross_down' }
]

export const alertTypeLabel = (value: string) =>
  alertTypeOptions.find(item => item.value === value)?.label || value

export const severityLabel: Record<AlertSeverity, string> = {
  info: '提示',
  warning: '警告',
  critical: '严重'
}

export const qualityLabel: Record<AlertQualityStatus, string> = {
  valid: '有效',
  partial: '部分有效',
  stale: '数据过期',
  missing: '数据缺失',
  error: '数据异常'
}

export const marketLabel: Record<AlertMarket, string> = {
  CN: 'A 股',
  HK: '港股',
  US: '美股',
  SYSTEM: '系统'
}

export function formatDateTime(value?: string | null): string {
  if (!value) return '尚无记录'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}

export function formatLatency(value: string | number | null | undefined): string {
  const seconds = Number(value)
  if (!Number.isFinite(seconds)) return '—'
  if (seconds < 1) return `${Math.round(seconds * 1000)} ms`
  return `${seconds.toFixed(seconds < 10 ? 2 : 1)} s`
}

export function ruleTarget(rule: AlertRule): string {
  const scope = rule.scope
  if (scope.scope_type === 'symbol') return scope.symbol
  if (scope.scope_type === 'watchlist') {
    return scope.watchlist_id ? `自选列表 ${scope.watchlist_id}` : `${scope.symbols.length} 只股票`
  }
  if (scope.scope_type === 'strategy_universe') return `策略版本 ${scope.strategy_version_id}`
  if (scope.scope_type === 'paper_position') return `模拟持仓 ${scope.account_id}`
  return `模拟账户 ${scope.account_id}`
}

export function eventTarget(event: AlertEvent): string {
  if (event.symbol) return event.symbol
  if (event.scope_key.startsWith('paper_account:')) return '模拟账户'
  if (event.scope_key.startsWith('system:')) return '系统'
  return event.scope_key
}

export function emptyRuleDraft(prefill?: {
  market?: string
  symbol?: string
}): AlertRuleDraft {
  const market = normalizeMarket(prefill?.market)
  return {
    name: prefill?.symbol ? `${prefill.symbol} 价格预警` : '',
    description: '',
    enabled: true,
    alert_type: 'price_above',
    market,
    scope: { scope_type: 'symbol', symbol: prefill?.symbol || '' },
    left_kind: 'current_value',
    operator: 'gt',
    threshold: '',
    upper_threshold: '',
    change_window_seconds: 300,
    factor_id: 'ret_1d',
    factor_version: 1,
    factor_lag: 0,
    evaluation_mode: 'edge',
    frequency_seconds: 60,
    duration_mode: 'none',
    duration_value: 1,
    schedule_type: 'market_hours',
    cooldown_seconds: 300,
    recovery_enabled: true,
    severity: 'warning',
    channels: ['in_app', 'websocket'],
    max_events_per_day: 100
  }
}

export function normalizeMarket(value?: string): 'CN' | 'HK' | 'US' {
  const normalized = String(value || '').toUpperCase()
  if (normalized === 'HK' || value === '港股') return 'HK'
  if (normalized === 'US' || value === '美股') return 'US'
  return 'CN'
}

export function conditionForDraft(draft: AlertRuleDraft): AlertCondition {
  const left = draft.left_kind === 'factor'
    ? { kind: 'factor' as const, factor_id: draft.factor_id, version: draft.factor_version, lag: draft.factor_lag }
    : draft.left_kind === 'change_rate'
      ? { kind: 'change_rate' as const, window_seconds: draft.change_window_seconds }
      : { kind: 'current_value' as const }
  const right = { kind: 'constant' as const, value: draft.threshold }
  if (draft.operator === 'cross_up' || draft.operator === 'cross_down') {
    return { type: draft.operator, left, right }
  }
  return {
    type: 'compare',
    left,
    operator: draft.operator,
    right,
    upper: draft.operator === 'between'
      ? { kind: 'constant', value: draft.upper_threshold }
      : null
  }
}

export function payloadForDraft(draft: AlertRuleDraft): Record<string, unknown> {
  const trigger: Record<string, unknown> = { condition: conditionForDraft(draft) }
  if (draft.duration_mode === 'seconds') trigger.for_seconds = draft.duration_value
  if (draft.duration_mode === 'evaluations') trigger.for_evaluations = draft.duration_value
  return {
    name: draft.name.trim(),
    description: draft.description.trim(),
    enabled: draft.enabled,
    alert_type: draft.alert_type,
    scope: draft.scope,
    market: draft.market,
    trigger,
    evaluation_mode: draft.evaluation_mode,
    frequency_seconds: draft.frequency_seconds,
    active_schedule: { schedule_type: draft.schedule_type },
    cooldown_seconds: draft.cooldown_seconds,
    recovery_enabled: draft.recovery_enabled,
    severity: draft.severity,
    channels: draft.channels,
    action: 'notify_only',
    origin: 'user',
    automation_id: null,
    paper_account_id: null,
    lookback_window: null,
    event_categories: [],
    max_events_per_day: draft.max_events_per_day,
    expires_at: null
  }
}

export function draftFromRule(rule: AlertRule): AlertRuleDraft {
  const condition = rule.trigger.condition
  const leaf = condition.type === 'all' || condition.type === 'any'
    ? condition.children[0]
    : condition.type === 'not'
      ? condition.child
      : condition
  const left = 'left' in leaf ? leaf.left : { kind: 'current_value' as const }
  const right = 'right' in leaf ? leaf.right : { kind: 'constant' as const, value: '' }
  const upper = 'upper' in leaf ? leaf.upper : null
  const operator = leaf.type === 'cross_up' || leaf.type === 'cross_down'
    ? leaf.type
    : leaf.type === 'compare'
      ? leaf.operator
      : 'gt'
  return {
    ...emptyRuleDraft(),
    rule_id: rule.rule_id,
    version: rule.version,
    name: rule.name,
    description: rule.description,
    enabled: rule.enabled,
    alert_type: rule.alert_type,
    market: rule.market === 'SYSTEM' ? 'CN' : rule.market,
    scope: rule.scope,
    left_kind: left.kind === 'factor' || left.kind === 'change_rate' ? left.kind : 'current_value',
    operator,
    threshold: right.kind === 'constant' ? right.value : '',
    upper_threshold: upper?.kind === 'constant' ? upper.value : '',
    change_window_seconds: left.kind === 'change_rate' ? left.window_seconds : 300,
    factor_id: left.kind === 'factor' ? left.factor_id : 'ret_1d',
    factor_version: left.kind === 'factor' ? left.version : 1,
    factor_lag: left.kind === 'factor' ? left.lag : 0,
    evaluation_mode: rule.evaluation_mode,
    frequency_seconds: rule.frequency_seconds,
    duration_mode: rule.trigger.for_seconds
      ? 'seconds'
      : rule.trigger.for_evaluations
        ? 'evaluations'
        : 'none',
    duration_value: rule.trigger.for_seconds || rule.trigger.for_evaluations || 1,
    schedule_type: rule.active_schedule.schedule_type === 'all_day' ? 'all_day' : 'market_hours',
    cooldown_seconds: rule.cooldown_seconds,
    recovery_enabled: rule.recovery_enabled,
    severity: rule.severity,
    channels: [...rule.channels],
    max_events_per_day: rule.max_events_per_day
  }
}
