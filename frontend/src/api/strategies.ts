import { request } from './request'
import type {
  DomainTask,
  PageResponse,
  Strategy,
  StrategyCreatePayload,
  StrategyDetail,
  StrategyPair,
  StrategySignal,
  StrategyTemplate,
  StrategyValidationResponse,
  StrategyVersion
} from '@/types/strategy'

const body = <T>(value: unknown): T => value as T
const id = (value: string): string => encodeURIComponent(value)

export const strategyApi = {
  async listTemplates(): Promise<StrategyTemplate[]> {
    return body(await request.get('/api/strategies/templates'))
  },
  async list(includeArchived = false): Promise<Strategy[]> {
    const response = body<{ items: Strategy[] }>(await request.get('/api/strategies', {
      params: { include_archived: includeArchived }
    }))
    return response.items
  },
  async get(strategyId: string): Promise<StrategyDetail> {
    return body(await request.get(`/api/strategies/${id(strategyId)}`))
  },
  async create(payload: StrategyCreatePayload): Promise<StrategyPair> {
    return body(await request.post('/api/strategies', payload))
  },
  async updateVersion(
    strategyId: string,
    versionId: string,
    expectedChecksum: string,
    definition: StrategyCreatePayload['definition'],
    analysisProfileVersionId: string | null,
    changeSummary: string
  ): Promise<StrategyVersion> {
    return body(await request.put(`/api/strategies/${id(strategyId)}/versions/${id(versionId)}`, {
      expected_checksum: expectedChecksum,
      definition,
      analysis_profile_version_id: analysisProfileVersionId,
      change_summary: changeSummary
    }))
  },
  async createVersion(
    strategyId: string,
    parentVersionId: string | null,
    changeSummary: string
  ): Promise<StrategyVersion> {
    return body(await request.post(`/api/strategies/${id(strategyId)}/versions`, {
      parent_version_id: parentVersionId,
      change_summary: changeSummary
    }))
  },
  async validateVersion(versionId: string): Promise<StrategyValidationResponse> {
    return body(await request.post('/api/strategies/validate', { strategy_version_id: versionId }))
  },
  async validateDefinition(
    market: string,
    definition: StrategyCreatePayload['definition']
  ): Promise<StrategyValidationResponse> {
    return body(await request.post('/api/strategies/validate', { market, definition }))
  },
  async publish(strategyId: string, versionId: string): Promise<StrategyVersion> {
    return body(await request.post(
      `/api/strategies/${id(strategyId)}/versions/${id(versionId)}/publish`
    ))
  },
  async clone(
    strategyId: string,
    sourceVersionId: string,
    name: string,
    description?: string
  ): Promise<StrategyPair> {
    return body(await request.post(`/api/strategies/${id(strategyId)}/clone`, {
      source_version_id: sourceVersionId,
      name,
      description
    }))
  },
  async archive(strategyId: string): Promise<Strategy> {
    return body(await request.delete(`/api/strategies/${id(strategyId)}`))
  },
  async createSignalTask(
    versionId: string,
    payload: {
      universe_snapshot_id: string
      factor_snapshot_ids: string[]
      as_of: string
      idempotency_key: string
    }
  ): Promise<DomainTask> {
    return body(await request.post(`/api/strategies/${id(versionId)}/signals`, payload))
  },
  async listSignals(query: {
    strategy_version_id?: string
    signal_date?: string
    page?: number
    page_size?: number
  }): Promise<PageResponse<StrategySignal>> {
    return body(await request.get('/api/strategies/signals', { params: query }))
  }
}
