export interface Campaign {
  campaign_id: string;
  user_id: string;
  name: string;
  description: string;
  status: 'draft' | 'activated' | 'paused' | 'stopped';
  strategy_id: string;
  strategy_version_num: number;
  portfolio_id: string;
  initial_allocation_cash: number;
  start_date: string;
  current_revision_num: number;
  rebalance_frequency: string;
  risk_config_override: Record<string, any>;
  activated_at?: string;
  paused_at?: string;
  stopped_at?: string;
  created_at: string;
  updated_at: string;
}

export interface CandidateRecord {
  candidate_id: string;
  cycle_id: string;
  campaign_id: string;
  symbol: string;
  score: number;
  rank: number;
  selected: boolean;
  rejection_reason?: string;
  target_weight: number;
}
