export type StrategyKind = 'screening' | 'ranking' | 'portfolio'
export type StrategyMarket = 'CN' | 'HK' | 'US'
export type StrategyVisibility = 'private' | 'shared_readonly' | 'system'
export type StrategyVersionStatus = 'draft' | 'validating' | 'published' | 'deprecated'

export interface StrategyCloneSource {
  strategy_id: string
  strategy_version_id: string
  version: number
  checksum: string
}

export interface Strategy {
  strategy_id: string
  user_id: string
  name: string
  description: string
  tags: string[]
  kind: StrategyKind
  visibility: StrategyVisibility
  current_draft_version_id: string | null
  latest_published_version_id: string | null
  clone_source: StrategyCloneSource | null
  version_sequence: number
  created_at: string
  updated_at: string
  archived_at: string | null
}

export interface FrozenFactorDependency {
  factor_id: string
  version: number
  checksum: string
}

export interface FrozenSkillDependency {
  skill_id: string
  version: number
  checksum: string
}

export interface StrategyValidationIssue {
  code: string
  message: string
  path: string | null
}

export interface StrategyValidationResult {
  valid: boolean
  errors: StrategyValidationIssue[]
  warnings: StrategyValidationIssue[]
  validated_at?: string
}

export interface StrategyVersion {
  strategy_version_id: string
  strategy_id: string
  user_id: string
  version: number
  status: StrategyVersionStatus
  market: StrategyMarket
  definition: StrategyDefinition
  analysis_profile_version_id: string | null
  factor_dependencies: FrozenFactorDependency[]
  skill_dependencies: FrozenSkillDependency[]
  checksum: string | null
  validation_result: StrategyValidationResult | null
  created_by: string
  created_at: string
  published_at: string | null
  change_summary: string
  parent_version_id: string | null
}

export interface StrategyPair {
  strategy: Strategy
  version: StrategyVersion
}

export interface StrategyDetail {
  strategy: Strategy
  versions: StrategyVersion[]
}

export interface TemplateParameterRange {
  name: string
  default: number
  minimum: number
  maximum: number
  unit: string
  sensitivity: string
}

export interface StrategyTemplate {
  template_id: string
  strategy_id: string
  strategy_version_id: string
  version: number
  name: string
  description: string
  formula: string
  kind: StrategyKind
  market: StrategyMarket
  definition: StrategyDefinition
  parameter_ranges: TemplateParameterRange[]
  suitable_markets: string[]
  unsuitable_scenarios: string[]
  risk_warning: string
}

export interface StrategyValidationResponse {
  valid: boolean
  errors: StrategyValidationIssue[]
  warnings: StrategyValidationIssue[]
  factor_dependencies: FrozenFactorDependency[]
  skill_dependencies: FrozenSkillDependency[]
}

export interface StrategySignal {
  signal_id: string
  user_id: string
  strategy_version_id: string
  universe_snapshot_id: string
  factor_snapshot_id: string | null
  market: StrategyMarket
  symbol: string
  signal_date: string
  signal_type: string
  score: number | null
  rank: number | null
  reason_codes: string[]
  input_contributions: Record<string, number>
  as_of: string
  checksum: string | null
  created_at: string
}

export interface PageResponse<T> {
  items: T[]
  page: number
  page_size: number
  total: number
}

export interface DomainTask {
  task_id: string
  task_type: string
  status: string
  progress: number
  stage: string
  message: string | null
  created_at: string
}

export interface StrategyFeatureRef {
  factor_id: string
  version: number
  params: Record<string, unknown>
}

export interface FactorOperand {
  kind: 'factor'
  factor_id: string
  version: number
  lag: number
}

export interface StrategyDefinition {
  universe: {
    snapshot_id: string | null
    minimum_listing_days: number
    exclude_st: boolean
    exclude_delisting: boolean
    exclude_suspended: boolean
    include_industries: string[]
    exclude_industries: string[]
    minimum_market_cap: number | null
    maximum_market_cap: number | null
  }
  data: {
    frequency: 'daily'
    adjustment: 'qfq' | 'hfq' | 'none'
    minimum_history: number
    allowed_quality: Array<'ok' | 'valid'>
    point_in_time: true
  }
  features: StrategyFeatureRef[]
  entry: Record<string, unknown>
  exit: Record<string, unknown>
  rebalance: Record<string, unknown>
  portfolio: Record<string, unknown>
  execution: Record<string, unknown>
  risk: Record<string, unknown>
  benchmark: { market: StrategyMarket; symbol: string }
  analysis: {
    analysis_profile_version_id: string | null
    skill_version_ids: string[]
    require_explanation: boolean
  } | null
}

export interface StrategyCreatePayload {
  name: string
  description: string
  tags: string[]
  kind: StrategyKind
  market: StrategyMarket
  definition: StrategyDefinition
  analysis_profile_version_id: string | null
  change_summary: string
}

export interface StrategyWizardModel {
  name: string
  description: string
  tags: string[]
  kind: StrategyKind
  market: StrategyMarket
  snapshotId: string
  minimumListingDays: number
  excludeSt: boolean
  excludeDelisting: boolean
  excludeSuspended: boolean
  minimumMarketCap: number | null
  maximumMarketCap: number | null
  adjustment: 'qfq' | 'hfq' | 'none'
  minimumHistory: number
  factors: string[]
  factorVersion: number
  entryFactor: string
  entryOperator: 'gt' | 'gte' | 'lt' | 'lte'
  entryThreshold: number
  takeProfit: number | null
  stopLoss: number | null
  maxHoldingPeriods: number | null
  rebalanceFrequency: 'daily' | 'weekly' | 'monthly'
  weekday: number
  dayOfMonth: number
  weighting: 'equal_weight' | 'score_weight'
  maxPositions: number
  maxPositionWeight: number
  maxIndustryWeight: number
  minCashRatio: number
  signalTime: 'open' | 'close'
  executionTime: 'same_open' | 'same_close' | 'next_open' | 'next_close'
  price: 'open' | 'close' | 'vwap'
  slippageBps: number
  feeModelVersion: string
  maxDrawdownStop: number | null
  volatilityTarget: number | null
  cooldownPeriods: number
  benchmarkSymbol: string
  analysisProfileVersionId: string
  skillVersionIds: string[]
  requireExplanation: boolean
  changeSummary: string
}
