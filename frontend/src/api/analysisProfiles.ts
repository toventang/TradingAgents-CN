import { request } from './request'
import type {
  AnalysisProfile,
  AnalysisProfileChanges,
  AnalysisProfileDetail,
  AnalysisProfileForm,
  AnalysisProfilePage,
  AnalysisProfilePair,
  AnalysisProfileVersion
} from '@/types/analysisProfile'

const body = <T>(value: unknown): T => value as T
const id = (value: string): string => encodeURIComponent(value)

export const analysisProfileApi = {
  async list(page = 1, pageSize = 100): Promise<AnalysisProfilePage> {
    return body(await request.get('/api/analysis-profiles', {
      params: { page, page_size: pageSize }
    }))
  },
  async get(profileId: string): Promise<AnalysisProfileDetail> {
    return body(await request.get(`/api/analysis-profiles/${id(profileId)}`))
  },
  async create(payload: AnalysisProfileForm): Promise<AnalysisProfilePair> {
    return body(await request.post('/api/analysis-profiles', payload))
  },
  async updateVersion(
    profileId: string,
    versionId: string,
    checksum: string,
    changes: Partial<AnalysisProfileChanges>,
    changeSummary: string
  ): Promise<AnalysisProfileVersion> {
    return body(await request.put(
      `/api/analysis-profiles/${id(profileId)}/versions/${id(versionId)}`,
      { expected_checksum: checksum, changes, change_summary: changeSummary }
    ))
  },
  async createVersion(profileId: string, changeSummary: string): Promise<AnalysisProfileVersion> {
    return body(await request.post(`/api/analysis-profiles/${id(profileId)}/versions`, {
      change_summary: changeSummary
    }))
  },
  async publish(profileId: string, versionId: string): Promise<AnalysisProfileVersion> {
    return body(await request.post(
      `/api/analysis-profiles/${id(profileId)}/versions/${id(versionId)}/publish`
    ))
  },
  async archive(profileId: string): Promise<AnalysisProfile> {
    return body(await request.delete(`/api/analysis-profiles/${id(profileId)}`))
  }
}
