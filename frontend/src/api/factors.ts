import { request } from './request'
import type {
  CompositeDefinition,
  CompositeDefinitionPayload,
  CompositeFactorResource,
  CompositeValidationResponse,
  DomainTask,
  FactorAnalysisAccepted,
  FactorAnalysisRequest,
  FactorAnalysisResult,
  FactorComputeAccepted,
  FactorComputeRequest,
  FactorDefinition,
  FactorDefinitionQuery,
  FactorJob,
  FactorSnapshot,
  FactorSnapshotQuery,
  FactorValidationResult,
  FactorValuePage,
  FactorValueQuery,
  FactorVersionRef,
  PageResponse
} from '@/types/factor'

// The shared response interceptor returns the decoded response body. These
// endpoints intentionally use FastAPI's typed, unwrapped response models.
const body = <T>(value: unknown): T => value as T

export const factorApi = {
  async listDefinitions(query: FactorDefinitionQuery = {}): Promise<PageResponse<FactorDefinition>> {
    return body(await request.get('/api/factors/definitions', { params: query }))
  },

  async getDefinition(factorId: string): Promise<FactorDefinition> {
    return body(await request.get(`/api/factors/definitions/${encodeURIComponent(factorId)}`))
  },

  async validate(market: string, factorSpecs: FactorVersionRef[]): Promise<FactorValidationResult> {
    return body(await request.post('/api/factors/validate', {
      market,
      factor_specs: factorSpecs
    }))
  },

  async compute(payload: FactorComputeRequest): Promise<FactorComputeAccepted> {
    return body(await request.post('/api/factors/compute', payload))
  },

  async getJob(jobId: string): Promise<FactorJob> {
    return body(await request.get(`/api/factors/jobs/${encodeURIComponent(jobId)}`))
  },

  async getTask(taskId: string): Promise<DomainTask> {
    return body(await request.get(`/api/tasks/${encodeURIComponent(taskId)}`))
  },

  async listSnapshots(query: FactorSnapshotQuery = {}): Promise<PageResponse<FactorSnapshot>> {
    return body(await request.get('/api/factors/snapshots', { params: query }))
  },

  async listValues(snapshotId: string, query: FactorValueQuery = {}): Promise<FactorValuePage> {
    const params = {
      ...query,
      factors: query.factors?.length ? query.factors.join(',') : undefined
    }
    return body(await request.get(
      `/api/factors/snapshots/${encodeURIComponent(snapshotId)}/values`,
      { params }
    ))
  },

  async analyze(payload: FactorAnalysisRequest): Promise<FactorAnalysisAccepted> {
    return body(await request.post('/api/factors/analyze', payload))
  },

  async getAnalysis(analysisId: string): Promise<FactorAnalysisResult> {
    return body(await request.get(`/api/factors/analysis/${encodeURIComponent(analysisId)}`))
  },

  async validateComposite(
    market: string,
    definition: CompositeDefinition
  ): Promise<CompositeValidationResponse> {
    return body(await request.post('/api/factor-composites/validate', { market, definition }))
  },

  async createComposite(payload: CompositeDefinitionPayload): Promise<CompositeFactorResource> {
    return body(await request.post('/api/factor-composites', payload))
  },

  async updateComposite(
    compositeId: string,
    payload: CompositeDefinitionPayload
  ): Promise<CompositeFactorResource> {
    return body(await request.put(
      `/api/factor-composites/${encodeURIComponent(compositeId)}`,
      payload
    ))
  },

  async publishComposite(compositeId: string): Promise<CompositeFactorResource> {
    return body(await request.post(
      `/api/factor-composites/${encodeURIComponent(compositeId)}/publish`
    ))
  }
}
