import axios from 'axios'
import { request } from './request'
import type {
  BacktestAccepted,
  BacktestCancelResult,
  BacktestCompareResult,
  BacktestEquityPage,
  BacktestEvent,
  BacktestExportDeferred,
  BacktestExportFormat,
  BacktestExportResource,
  BacktestExportResult,
  BacktestPage,
  BacktestPerformanceReport,
  BacktestPosition,
  BacktestRequest,
  BacktestRun,
  BacktestRunDetail,
  BacktestRunStatus,
  BacktestTrade,
  DomainTask,
  EquityDownsample
} from '@/types/backtest'

export type ParameterSearchMode = 'split' | 'walk_forward'
export type ParameterSearchStatus = 'queued' | 'running' | 'succeeded' | 'cancelled' | 'failed'
export type EvaluationSegment = 'train' | 'validation' | 'test'
export type ParameterValue = boolean | number | string

export interface ParameterGridAxis {
  name: string
  values: ParameterValue[]
}

export interface ParameterSearchRequest {
  name: string
  base_request: BacktestRequest
  axes: ParameterGridAxis[]
  mode: ParameterSearchMode
  split?: { train_end: string; validation_end: string } | null
  walk_forward?: {
    train_sessions: number
    validation_sessions: number
    test_sessions: number
    step_sessions: number
    max_folds: number
  } | null
  combination_limit: number
}

export interface EvaluationWindow {
  fold: number
  segment: EvaluationSegment
  start_date: string
  end_date: string
  session_count: number
}

export interface ParameterSearchRecord {
  search_id: string
  task_id: string
  user_id: string
  name: string
  strategy_version_id: string
  market: string
  request: ParameterSearchRequest
  input_versions: Record<string, string[]>
  status: ParameterSearchStatus
  total_combinations: number
  completed_combinations: number
  successful_combinations: number
  shared_input_checksum: string
  windows: EvaluationWindow[]
  selected_combination_index: number | null
  research_notice: string
  error: Record<string, unknown> | null
  created_at: string
  started_at: string | null
  finished_at: string | null
  updated_at: string
}

export interface ParameterSearchAccepted {
  search_id: string
  task_id: string
  status: ParameterSearchStatus
  total_combinations: number
  deduplicated: boolean
  research_notice: string
}

export interface ParameterSearchDetail {
  search: ParameterSearchRecord
  task: DomainTask | null
}

export interface WindowPerformance extends EvaluationWindow {
  observations: number
  total_return: string | null
  max_drawdown: string | null
  annualized_volatility: string | null
}

export interface StabilityEvidence {
  neighboring_combinations: number
  neighboring_validation_dispersion: string | null
  fold_validation_dispersion: string | null
  positive_test_fold_ratio: string | null
  stability_score: string
}

export interface ParameterCombinationResult {
  search_id: string
  user_id: string
  combination_index: number
  parameters: Record<string, ParameterValue>
  child_run_id: string
  status: BacktestRunStatus
  validation_mean_return: string | null
  test_mean_return: string | null
  train_mean_return: string | null
  windows: WindowPerformance[]
  stability: StabilityEvidence | null
  validation_rank: number | null
  selected_candidate: boolean
  error: Record<string, unknown> | null
  completed_at: string | null
}

export interface ParameterSearchPage<T> {
  items: T[]
  page: number
  page_size: number
  total: number
}

export interface ParameterResultPage extends ParameterSearchPage<ParameterCombinationResult> {
  selected_combination_index: number | null
  research_notice: string
}

export interface ParameterSearchCancelResult {
  search_id: string
  task_id: string
  search_status: ParameterSearchStatus
  task_status: DomainTask['status']
}

const body = <T>(value: unknown): T => value as T
const id = (value: string): string => encodeURIComponent(value)

export const backtestApi = {
  async create(payload: BacktestRequest, idempotencyKey: string): Promise<BacktestAccepted> {
    return body(await request.post('/api/backtests', payload, {
      headers: { 'Idempotency-Key': idempotencyKey }
    }))
  },

  async list(query: {
    status?: BacktestRunStatus
    page?: number
    page_size?: number
  } = {}): Promise<BacktestPage<BacktestRun>> {
    return body(await request.get('/api/backtests', { params: query }))
  },

  async get(runId: string): Promise<BacktestRunDetail> {
    return body(await request.get(`/api/backtests/${id(runId)}`))
  },

  async cancel(runId: string): Promise<BacktestCancelResult> {
    return body(await request.post(`/api/backtests/${id(runId)}/cancel`))
  },

  async equity(runId: string, query: {
    start_date?: string
    end_date?: string
    downsample?: EquityDownsample
    page?: number
    page_size?: number
  } = {}): Promise<BacktestEquityPage> {
    return body(await request.get(`/api/backtests/${id(runId)}/equity`, { params: query }))
  },

  async trades(runId: string, query: {
    start_date?: string
    end_date?: string
    page?: number
    page_size?: number
  } = {}): Promise<BacktestPage<BacktestTrade>> {
    return body(await request.get(`/api/backtests/${id(runId)}/trades`, { params: query }))
  },

  async positions(runId: string, query: {
    trade_date?: string
    start_date?: string
    end_date?: string
    page?: number
    page_size?: number
  } = {}): Promise<BacktestPage<BacktestPosition>> {
    return body(await request.get(`/api/backtests/${id(runId)}/positions`, { params: query }))
  },

  async events(runId: string, query: {
    start_date?: string
    end_date?: string
    page?: number
    page_size?: number
  } = {}): Promise<BacktestPage<BacktestEvent>> {
    return body(await request.get(`/api/backtests/${id(runId)}/events`, { params: query }))
  },

  async metrics(runId: string): Promise<BacktestPerformanceReport> {
    return body(await request.get(`/api/backtests/${id(runId)}/metrics`))
  },

  async compare(runIds: string[]): Promise<BacktestCompareResult> {
    return body(await request.post('/api/backtests/compare', { run_ids: runIds }))
  },

  async createParameterSearch(
    payload: ParameterSearchRequest,
    idempotencyKey: string
  ): Promise<ParameterSearchAccepted> {
    return body(await request.post('/api/backtests/parameter-search', payload, {
      headers: { 'Idempotency-Key': idempotencyKey }
    }))
  },

  async listParameterSearches(query: {
    status?: ParameterSearchStatus
    page?: number
    page_size?: number
  } = {}): Promise<ParameterSearchPage<ParameterSearchRecord>> {
    return body(await request.get('/api/backtests/parameter-search', { params: query }))
  },

  async getParameterSearch(searchId: string): Promise<ParameterSearchDetail> {
    return body(await request.get(`/api/backtests/parameter-search/${id(searchId)}`))
  },

  async getParameterSearchResults(searchId: string, query: {
    page?: number
    page_size?: number
  } = {}): Promise<ParameterResultPage> {
    return body(await request.get(`/api/backtests/parameter-search/${id(searchId)}/results`, {
      params: query
    }))
  },

  async cancelParameterSearch(searchId: string): Promise<ParameterSearchCancelResult> {
    return body(await request.post(`/api/backtests/parameter-search/${id(searchId)}/cancel`))
  },

  async export(
    runId: string,
    resource: BacktestExportResource,
    format: BacktestExportFormat
  ): Promise<BacktestExportResult> {
    const token = localStorage.getItem('auth-token')
    const response = await axios.get(`/api/backtests/${id(runId)}/export`, {
      baseURL: import.meta.env.VITE_API_BASE_URL || '',
      params: { resource, format },
      responseType: 'blob',
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      validateStatus: status => status === 200 || status === 202
    })
    if (response.status === 202) {
      const payload = JSON.parse(await response.data.text()) as Omit<BacktestExportDeferred, 'kind'>
      return { ...payload, kind: 'deferred' }
    }
    const disposition = String(response.headers['content-disposition'] || '')
    const filename = disposition.match(/filename="?([^";]+)"?/i)?.[1]
      || `backtest-${runId}-${resource}.${format}`
    return { kind: 'file', blob: response.data, filename }
  }
}
