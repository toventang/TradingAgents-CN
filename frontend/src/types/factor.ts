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
