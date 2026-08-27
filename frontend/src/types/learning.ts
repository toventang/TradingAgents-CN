export interface ExcursionMetrics {
  mae_pct: number;
  mfe_pct: number;
  holding_days: number;
  realized_pnl_pct: number;
  benchmark_return_pct: number;
  excess_return_pct: number;
  slippage_cost_pct: number;
}

export interface TradeAttributionResult {
  review_id: string;
  trade_id: string;
  symbol: string;
  metrics: ExcursionMetrics;
  primary_cause: string;
  cause_breakdown: Record<string, number>;
}

export interface AITradeReview {
  review_id: string;
  trade_id: string;
  symbol: string;
  summary: string;
  diagnosis: string;
  grounding: {
    supporting_evidence: string[];
    counter_evidence: string[];
    is_sufficient: boolean;
  };
  confidence: string;
  controllability_score: number;
  suggested_improvements: string[];
}

export interface ProposalDiffItem {
  parameter_path: string;
  current_value: any;
  proposed_value: any;
  approved: boolean;
  reasoning: string;
}

export interface LearningProposal {
  proposal_id: string;
  campaign_id: string;
  strategy_id: string;
  status: string;
  sample_count: number;
  diff_items: ProposalDiffItem[];
  created_at: string;
}
