export type FactorMarket = 'CN' | 'HK' | 'US'

export type FactorCategory =
  | 'price'
  | 'trend'
  | 'momentum'
  | 'volatility'
  | 'liquidity'
  | 'valuation'
  | 'quality'
  | 'growth'
  | 'sentiment'
  | 'event'
  | 'cross_section'
  | 'composite'

export type FactorStatus = 'draft' | 'active' | 'deprecated'
export type FactorSnapshotStatus = 'building' | 'ready' | 'failed' | 'superseded'
export type FactorJobStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled'
export type DomainTaskStatus =
  | 'queued'
  | 'running'
  | 'succeeded'
  | 'cancelling'
  | 'cancelled'
  | 'retry_wait'
  | 'failed'

export interface FactorParameterSpec {
  type: 'integer' | 'number' | 'string' | 'boolean' | 'object'
  required: boolean
  minimum: number | null
  maximum: number | null
  min_properties: number | null
  choices: unknown[]
  description: string
}

export interface FactorDefinition {
  factor_id: string
  version: number
  name: string
  display_name: string
  description: string
  category: FactorCategory
  catalog_group: string
  frequency: 'daily' | 'intraday' | 'quarterly'
  required_columns: string[]
  dependencies: string[]
  params_schema: Record<string, FactorParameterSpec>
  default_params: Record<string, unknown>
  min_history: number
  formula_ref: string
  output_column: string
  direction: 'positive' | 'negative' | 'neutral'
  winsorize_default: 'none' | 'mad' | 'quantile'
  normalize_default: 'none' | 'zscore' | 'rank' | 'robust_zscore'
  missing_policy: 'drop' | 'neutral' | 'industry_median' | 'zero'
  supported_markets: FactorMarket[]
  point_in_time_required: boolean
  status: FactorStatus
  checksum: string
}

export interface PageResponse<T> {
  items: T[]
  page: number
  page_size: number
  total: number
}

export interface FactorDefinitionQuery {
  category?: FactorCategory
  market?: FactorMarket
  status?: FactorStatus
  search?: string
  page?: number
  page_size?: number
}

export interface FactorVersionRef {
  factor_id: string
  version: number
  params: Record<string, unknown>
}

export interface FactorValidationIssue {
  code: string
  message: string
  factor_id: string | null
}

export interface FactorValidationResult {
  valid: boolean
  issues: FactorValidationIssue[]
  execution_order: string[]
  required_columns: string[]
  common_intermediates: string[]
  plan_checksum: string | null
}

export interface FactorComputeRequest {
  market: FactorMarket
  universe: {
    snapshot_id: string
    symbols: string[]
  }
  start_date: string
  end_date: string
  as_of: string
  factor_specs: FactorVersionRef[]
  source_versions: Record<string, string>
  adj: 'qfq' | 'hfq' | 'none'
  force_recompute: boolean
  chunk_size: number
  workers: number
}

export interface FactorComputeAccepted {
  job_id: string
  task_id: string
  request_checksum: string
  deduplicated: boolean
}

export interface FactorJob {
  job_id: string
  user_id: string
  task_id: string
  request_checksum: string
  status: FactorJobStatus
  request: {
    universe_snapshot_id: string
    members: Array<{ market: FactorMarket; symbol: string }>
    start_date: string | null
    trade_date: string
    as_of: string
    factors: FactorVersionRef[]
    source_versions: Record<string, string>
    adjustment: 'qfq' | 'hfq' | 'none'
    chunk_size: number
    workers: number
    request_nonce: string | null
  }
  snapshot_id: string | null
  completed_symbols: number
  total_symbols: number
  error: Record<string, unknown> | null
  created_at: string
  updated_at: string
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

export interface FactorSnapshot {
  snapshot_id: string
  user_id: string
  job_id: string
  task_id: string
  market: FactorMarket
  trade_date: string
  as_of: string
  universe_snapshot_id: string
  factor_set_checksum: string
  request_checksum: string
  status: FactorSnapshotStatus
  expected_row_count: number
  expected_factor_count: number
  row_count: number
  factor_count: number
  source_versions: Record<string, string>
  values_checksum: string | null
  error: Record<string, unknown> | null
  created_at: string
  updated_at: string
  published_at: string | null
}

export interface FactorSnapshotQuery {
  market?: FactorMarket
  trade_date?: string
  status?: FactorSnapshotStatus
  page?: number
  page_size?: number
}

export interface FactorValueRow {
  snapshot_id: string
  market: FactorMarket
  symbol: string
  trade_date: string
  values: Record<string, number | null>
  quality: Record<string, string | null>
  created_at: string | null
}

export interface FactorValuePage extends PageResponse<FactorValueRow> {
  snapshot: FactorSnapshot
}

export interface FactorValueQuery {
  symbol?: string
  factors?: string[]
  page?: number
  page_size?: number
}

export interface PersistedFactorTask {
  jobId: string
  taskId: string
  requestChecksum: string
  savedAt: string
}

export type FactorAnalysisHorizon = 1 | 5 | 10 | 20

export interface FactorAnalysisRequest {
  snapshot_ids: string[]
  factor_ids: string[]
  horizons: FactorAnalysisHorizon[]
  quantiles: 5 | 10
  min_samples: number
  min_cross_section: number
  label_as_of: string
  label_source_version: string
  transaction_cost_bps: number
  correlation_threshold: number
  industry_by_symbol: Record<string, string>
  exposure_source_version?: string
}

export interface FactorAnalysisAccepted {
  analysis_id: string
  task_id: string
  request_checksum: string
  deduplicated: boolean
}

export interface FactorDistributionSummary {
  factor_id: string
  total_observations: number
  valid_observations: number
  missing_rate: number
  extreme_rate: number
  coverage_symbols: number
  mean: number | null
  std: number | null
  minimum: number | null
  p01: number | null
  p25: number | null
  median: number | null
  p75: number | null
  p99: number | null
  maximum: number | null
}

export interface FactorTimePoint {
  factor_id: string
  trade_date: string
  mean: number | null
  median: number | null
  std: number | null
  valid_observations: number
  missing_rate: number
}

export interface FactorDailyIC {
  trade_date: string
  sample_count: number
  pearson: number | null
  rank: number | null
}

export interface FactorICMetric {
  factor_id: string
  horizon: FactorAnalysisHorizon
  sample_count: number
  period_count: number
  sample_start: string | null
  sample_end: string | null
  pearson_mean: number | null
  pearson_std: number | null
  pearson_icir: number | null
  pearson_positive_ratio: number | null
  rank_mean: number | null
  rank_std: number | null
  rank_icir: number | null
  rank_positive_ratio: number | null
  daily: FactorDailyIC[]
}

export interface FactorQuantileMetric {
  factor_id: string
  horizon: FactorAnalysisHorizon
  quantiles: 5 | 10
  sample_count: number
  returns: Record<string, number | null>
  monotonicity: number | null
  gross_long_short_return: number | null
  net_long_short_return: number | null
}

export interface FactorTurnoverMetric {
  factor_id: string
  quantiles: 5 | 10
  period_count: number
  top_turnover: number | null
  bottom_turnover: number | null
  long_short_turnover: number | null
}

export interface FactorCorrelationMetric {
  factor_a: string
  factor_b: string
  correlation: number | null
  sample_count: number
  period_count: number
}

export interface FactorCorrelationWarning {
  factor_a: string
  factor_b: string
  correlation: number
  threshold: number
}

export interface FactorExposureMetric {
  factor_id: string
  industry_exposure: Record<string, number | null>
  industry_sample_counts: Record<string, number>
  market_cap_correlation: number | null
  market_cap_sample_count: number
  beta_correlation: number | null
  beta_sample_count: number
}

export interface FactorDecayMetric {
  factor_id: string
  rank_ic_by_horizon: Record<string, number | null>
  pearson_ic_by_horizon: Record<string, number | null>
}

export interface FactorAnalysisResult {
  analysis_id: string
  user_id: string
  task_id: string
  request_checksum: string
  request: FactorAnalysisRequest
  market: FactorMarket
  universe_snapshot_id: string
  feature_start: string
  feature_end: string
  feature_as_of_start: string
  feature_as_of_end: string
  factor_set_checksums: Record<string, string>
  source_versions: Record<string, string[]>
  transaction_cost_included: boolean
  distributions: FactorDistributionSummary[]
  time_series: FactorTimePoint[]
  ic: FactorICMetric[]
  quantile_returns: FactorQuantileMetric[]
  turnover: FactorTurnoverMetric[]
  correlations: FactorCorrelationMetric[]
  correlation_warnings: FactorCorrelationWarning[]
  exposures: FactorExposureMetric[]
  decay: FactorDecayMetric[]
  quality: {
    snapshot_count: number
    row_count: number
    excluded_quality_values: number
    missing_factor_values: number
    missing_labels_by_horizon: Record<string, number>
    label_source_versions: string[]
  }
  created_at: string
  result_checksum: string
}

export type CompositeTransformKind =
  | 'identity'
  | 'negate'
  | 'log1p_abs'
  | 'winsorize_mad'
  | 'winsorize_quantile'
  | 'zscore'
  | 'robust_zscore'
  | 'percentile_rank'

export type CompositeNeutralizeKind = 'none' | 'industry' | 'market_cap' | 'industry_and_market_cap'
export type CompositeArithmeticKind = 'weighted_sum' | 'mean' | 'geometric_mean'
export type CompositeMissingKind = 'drop_symbol' | 'renormalize_weights' | 'neutral_score'
export type CompositeStatus = 'draft' | 'published'

export interface CompositeTransformSpec {
  kind: CompositeTransformKind
  mad_scale?: number
  lower_quantile?: number
  upper_quantile?: number
}

export interface CompositeFactorTerm {
  factor: FactorVersionRef
  weight: number
  transform: CompositeTransformSpec
}

export interface CompositeFilterPolicy {
  minimum_factor_coverage: number
  minimum_market_cap_log?: number
  maximum_market_cap_log?: number
  include_industries: string[]
  exclude_industries: string[]
  minimum_listing_days?: number
  exclude_st: boolean
  exclude_delisting: boolean
  exclude_suspended: boolean
}

export interface CompositeDefinition {
  terms: CompositeFactorTerm[]
  auto_direction: boolean
  neutralize: CompositeNeutralizeKind
  arithmetic: CompositeArithmeticKind
  missing: CompositeMissingKind
  filters: CompositeFilterPolicy
}

export interface CompositeDefinitionPayload {
  name: string
  description: string
  market: FactorMarket
  definition: CompositeDefinition
}

export interface CompositeDependencyVersion {
  factor_id: string
  version: number
  params: Record<string, unknown>
  definition_checksum: string
  direction: 'positive' | 'negative' | 'neutral'
  effective_multiplier: -1 | 1
}

export interface CompositeValidationResponse {
  valid: boolean
  issues: FactorValidationIssue[]
  normalized_definition: CompositeDefinition | null
  dependencies: CompositeDependencyVersion[]
  definition_checksum: string | null
}

export interface CompositeFactorResource extends CompositeDefinitionPayload {
  composite_id: string
  user_id: string
  version: number
  status: CompositeStatus
  dependencies: CompositeDependencyVersion[]
  definition_checksum: string
  created_at: string
  updated_at: string
  published_at: string | null
}
