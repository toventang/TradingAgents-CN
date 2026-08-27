export interface Strategy {
  strategy_id: string;
  user_id: string;
  name: string;
  description: string;
  strategy_type: string;
  is_system_template: boolean;
  status: string;
  latest_version_num: number;
  published_version_num?: number;
  created_at: string;
  updated_at: string;
}

export interface StrategyVersion {
  version_id: string;
  strategy_id: string;
  version_num: number;
  is_published: boolean;
  parameters: Record<string, any>;
  rules: Record<string, any>;
  universe: Record<string, any>;
  commit_message?: string;
  created_at: string;
}
