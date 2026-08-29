import { request } from './request'
import type {
  DomainTask,
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
  }
}
