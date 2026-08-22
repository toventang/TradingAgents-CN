export interface CostSlippageModel {
  broker_id: string;
  account_id: string;
  commission_rate: number;
  min_commission: number;
  stamp_duty_rate: number;
  transfer_fee_rate: number;
  slippage_rate: number;
}

export interface BacktestConfig {
  strategy_id: string;
  version_num: number;
  start_date: string;
  end_date: string;
  initial_capital: number;
  benchmark: string;
  rebalance_frequency: string;
  cost_model: CostSlippageModel;
}

export interface TradeFill {
  fill_id: string;
  trade_date: string;
  symbol: string;
  side: 'buy' | 'sell';
  quantity: number;
  price: number;
  execution_price: number;
  turnover: number;
  commission: number;
  stamp_duty: number;
  transfer_fee: number;
  total_cost: number;
}

export interface EquityPoint {
  trade_date: string;
  cash: number;
  market_value: number;
  total_equity: number;
  benchmark_equity: number;
  daily_return: number;
  benchmark_return: number;
}

export interface PerformanceMetrics {
  total_return: number;
  annualized_return: number;
  benchmark_return: number;
  excess_return: number;
  max_drawdown: number;
  max_drawdown_duration_days: number;
  sharpe_ratio: number;
  sortino_ratio: number;
  information_ratio: number;
  win_rate: number;
  profit_loss_ratio: number;
  total_trades: number;
  turnover_rate: number;
}

export interface BacktestResult {
  backtest_id: string;
  user_id: string;
  config: BacktestConfig;
  status: string;
  equity_curve: EquityPoint[];
  fills: TradeFill[];
  metrics?: PerformanceMetrics;
  created_at: string;
  completed_at?: string;
}
