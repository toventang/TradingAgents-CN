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
  EquityDownsample
} from '@/types/backtest'

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
