export interface ParameterSchema {
  name: string
  type: string
  default: any
  description?: string
}

export interface FactorDefinition {
  factor_id: string
  name: string
  category: string
  description: string
  parameters?: ParameterSchema[]
  required_history_days?: number
  supported_markets?: string[]
  direction?: number
  missing_policy?: string
  version?: string
  checksum?: string
}

export interface ComputeFactorPayload {
  symbols: string[]
  market: string
  factor_ids: string[]
  idempotency_key?: string
}

export interface FactorComputeJobResponse {
  task_id: string
  status: string
  message: string
}

export interface FactorSnapshot {
  snapshot_id: string
  user_id: string
  market: string
  factor_ids: string[]
  data: Record<string, Record<string, number[]>>
  checksum: string
  status: string
  created_at: string
}

export interface FactorSnapshotValuesResponse {
  items: Record<string, Record<string, number[]>>
  total: number
  page: number
  page_size: number
}
