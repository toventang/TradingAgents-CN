export interface RiskConfig {
  portfolio_id: string;
  max_stock_weight: number;
  max_sector_weight: number;
  max_drawdown_limit: number;
  max_var_95_limit: number;
  max_adv_participation_rate: number;
  enforce_t_plus_1: boolean;
  block_limit_up_buy: boolean;
  block_limit_down_sell: boolean;
}

export interface RiskViolation {
  rule_id: string;
  rule_name: string;
  severity: 'info' | 'warning' | 'critical';
  symbol?: string;
  current_value: number;
  limit_threshold: number;
  action_required: string;
  message: string;
}

export interface RiskEvaluationResult {
  evaluation_id: string;
  portfolio_id: string;
  decision: 'approved' | 'approved_with_warnings' | 'rejected';
  violations: RiskViolation[];
  evaluated_at: string;
}

export interface RiskAuditLog extends RiskEvaluationResult {
  user_id: string;
}
