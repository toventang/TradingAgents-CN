export type BacktestMarket = 'CN' | 'HK' | 'US'
export type BacktestRunStatus = 'queued' | 'running' | 'succeeded' | 'cancelled' | 'failed'
export type DomainTaskStatus =
  | 'queued'
  | 'running'
  | 'succeeded'
  | 'cancelling'
  | 'cancelled'
  | 'retry_wait'
  | 'failed'
export type EquityDownsample = 'none' | 'weekly' | 'monthly'
export type BacktestExportResource = 'equity' | 'orders' | 'trades' | 'positions' | 'events' | 'metrics'
export type BacktestExportFormat = 'csv' | 'json'

export interface BacktestRequest {
  strategy_version_id: string
  market: BacktestMarket
  start_date: string
  end_date: string
  initial_cash: string
  benchmark: string
  execution_model_id: string
  base_currency?: 'CNY' | 'HKD' | 'USD'
  parameter_overrides: Record<string, unknown>
  universe_override?: string | null
  seed: number
  save_daily_positions: boolean
  notes: string
}

export interface BacktestAccepted {
  run_id: string
  task_id: string
  status: BacktestRunStatus
  deduplicated: boolean
}

export interface DomainTaskError {
  code: string
  message: string
  retryable: boolean
  details: Record<string, unknown>
}

export interface DomainTask {
  task_id: string
  user_id: string
  task_type: string
  status: DomainTaskStatus
  priority: number
  payload: Record<string, unknown>
  progress: number
  stage: string
  message: string | null
  result_ref: { collection: string; id: string } | null
  attempt: number
  max_attempts: number
  error: DomainTaskError | null
  created_at: string
  started_at: string | null
  finished_at: string | null
  updated_at: string
}

export interface BacktestRun {
  run_id: string
  task_id: string
  user_id: string
  strategy_version_id: string
  market: BacktestMarket
  request: BacktestRequest
  input_versions: Record<string, string[]>
  bias_warnings: Array<Record<string, unknown>>
  status: BacktestRunStatus
  summary: Record<string, unknown>
  error: Record<string, unknown> | null
  last_completed_trade_date: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
  updated_at: string
}

export interface BacktestRunDetail {
  run: BacktestRun
  task: DomainTask | null
}

export interface BacktestCancelResult {
  run_id: string
  task_id: string
  run_status: BacktestRunStatus
  task_status: DomainTaskStatus
}

export interface BacktestPage<T> {
  items: T[]
  page: number
  page_size: number
  total: number
}

export interface FeeBreakdown {
  commission: string
  stamp_duty: string
  transfer_fee: string
  transaction_levy: string
  trading_fee: string
  settlement_fee: string
  sec_fee: string
  other: string
  total: string
}

export interface BacktestEquityPoint {
  run_id: string
  user_id: string
  trade_date: string
  cash: string
  market_value: string
  equity: string
  daily_return: string | null
  cumulative_return: string
  drawdown: string
  benchmark_equity: string | null
  turnover: string
  gross_exposure: string
  net_exposure: string
}

export interface BacktestEquityPage extends BacktestPage<BacktestEquityPoint> {
  downsample: EquityDownsample
}

export interface BacktestTrade {
  trade_id: string
  order_id: string
  run_id: string
  user_id: string
  market: BacktestMarket
  symbol: string
  side: 'buy' | 'sell'
  quantity: number
  raw_price: string
  slippage: string
  fill_price: string
  notional: string
  fees: FeeBreakdown
  trade_date: string
  realized_pnl: string | null
}

export interface BacktestPosition {
  run_id: string
  user_id: string
  trade_date: string
  market: BacktestMarket
  symbol: string
  quantity: number
  available_qty: number
  avg_cost: string
  close: string
  market_value: string
  unrealized_pnl: string
  weight: string
  holding_days: number
}

export interface BacktestEvent {
  event_id: string
  run_id: string
  user_id: string
  trade_date: string
  sequence: number
  step: number
  event_type: string
  symbol: string | null
  data: Record<string, unknown>
}

export interface BacktestPeriodReturn {
  period: string
  start_date: string
  end_date: string
  return_rate: string
}

export interface BacktestClosedLot {
  closed_lot_id: string
  symbol: string
  buy_trade_id: string
  sell_trade_id: string
  buy_order_id: string
  sell_order_id: string
  quantity: number
  entry_trade_date: string
  exit_trade_date: string
  entry_cost: string
  exit_proceeds: string
  pnl: string
  return_rate: string
  holding_sessions: number
  exit_reason: string
}

export interface BacktestPerformanceReport {
  initial_equity: string
  final_equity: string
  return_observations: number
  total_return: string
  cagr: string
  mean_daily_return: string
  annualized_volatility: string
  annual_risk_free_rate: string
  daily_risk_free_rate: string
  sharpe_ratio: string | null
  annualized_downside_deviation: string
  sortino_ratio: string | null
  max_drawdown: string
  max_drawdown_start_date: string | null
  max_drawdown_end_date: string | null
  max_drawdown_recovery_date: string | null
  calmar_ratio: string | null
  benchmark_observations: number
  benchmark_total_return: string | null
  relative_total_return: string | null
  beta: string | null
  annualized_alpha: string | null
  tracking_error: string | null
  information_ratio: string | null
  closed_lot_count: number
  winning_lot_count: number
  losing_lot_count: number
  breakeven_lot_count: number
  win_rate: string | null
  loss_rate: string | null
  profit_loss_ratio: string | null
  profit_factor: string | null
  gross_winning_pnl: string
  gross_losing_pnl: string
  net_closed_pnl: string
  average_closed_lot_pnl: string | null
  median_closed_lot_pnl: string | null
  average_closed_lot_return: string | null
  median_closed_lot_return: string | null
  maximum_winning_pnl: string | null
  maximum_losing_pnl: string | null
  average_holding_sessions: string | null
  median_holding_sessions: string | null
  total_turnover: string
  average_daily_turnover: string
  total_fees: string
  total_slippage_cost: string
  fee_to_gross_profit_ratio: string | null
  average_gross_exposure: string
  maximum_gross_exposure: string
  average_net_exposure: string
  maximum_net_exposure: string
  average_cash_ratio: string
  minimum_cash_ratio: string
  maximum_cash_ratio: string
  final_cash_ratio: string
  maximum_stock_concentration: string
  maximum_industry_concentration: string | null
  trade_count: number
  rejected_order_count: number
  partially_filled_order_count: number
  monthly_returns: BacktestPeriodReturn[]
  yearly_returns: BacktestPeriodReturn[]
  exit_reason_distribution: Record<string, number>
  closed_lots: BacktestClosedLot[]
  warnings: string[]
  formulas: Record<string, string>
}

export interface BacktestComparisonItem {
  run_id: string
  market: BacktestMarket
  start_date: string
  end_date: string
  metrics: BacktestPerformanceReport
}

export interface BacktestCompareResult {
  comparable: boolean
  compatibility_warnings: string[]
  items: BacktestComparisonItem[]
}

export interface BacktestExportDeferred {
  kind: 'deferred'
  code: string
  message: string
  resource: BacktestExportResource
  estimated_rows: number
  maximum_rows: number
}

export interface BacktestExportFile {
  kind: 'file'
  blob: Blob
  filename: string
}

export type BacktestExportResult = BacktestExportDeferred | BacktestExportFile

export interface PublishedStrategyOption {
  strategy_id: string
  strategy_version_id: string
  name: string
  market: BacktestMarket
  fee_model_version: string
}
