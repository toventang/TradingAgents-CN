import { ApiClient } from "./request"
import type {
  FactorDefinition,
  ComputeFactorPayload,
  FactorComputeJobResponse,
  FactorSnapshot,
  FactorSnapshotValuesResponse
} from "@/types/factor"

export const factorsApi = {
  // 获取因子定义元数据目录
  getFactorDefinitions(params?: { category?: string; market?: string; search?: string }) {
    return ApiClient.get<{ items: FactorDefinition[]; total: number }>("/api/factors/definitions", params)
  },

  // 获取单个因子定义详情
  getFactorDefinition(factorId: string) {
    return ApiClient.get<FactorDefinition>(`/api/factors/definitions/${factorId}`)
  },

  // 提交异步因子计算任务
  submitFactorComputeJob(data: ComputeFactorPayload) {
    return ApiClient.post<FactorComputeJobResponse>("/api/factors/compute", data)
  },

  // 获取因子快照详情
  getFactorSnapshot(snapshotId: string) {
    return ApiClient.get<FactorSnapshot>(`/api/factors/snapshots/${snapshotId}`)
  },

  // 分页获取因子快照数值
  getFactorSnapshotValues(snapshotId: string, page = 1, pageSize = 50) {
    return ApiClient.get<FactorSnapshotValuesResponse>(`/api/factors/snapshots/${snapshotId}/values`, {
      page,
      page_size: pageSize
    })
  }
}

export default factorsApi
