import type {
  DomainTaskStatus,
  FactorCategory,
  FactorMarket,
  FactorSnapshotStatus,
  FactorStatus
} from '@/types/factor'

export const marketLabels: Record<FactorMarket, string> = {
  CN: 'A 股',
  HK: '港股',
  US: '美股'
}

export const categoryLabels: Record<FactorCategory, string> = {
  price: '价格',
  trend: '趋势',
  momentum: '动量',
  volatility: '波动率',
  liquidity: '流动性',
  valuation: '估值',
  quality: '质量',
  growth: '成长',
  sentiment: '情绪',
  event: '事件',
  cross_section: '截面',
  composite: '复合'
}

export const factorStatusLabels: Record<FactorStatus, string> = {
  draft: '草稿',
  active: '启用',
  deprecated: '已弃用'
}

export const snapshotStatusLabels: Record<FactorSnapshotStatus, string> = {
  building: '生成中',
  ready: '可用',
  failed: '失败',
  superseded: '已取代'
}

export const taskStatusLabels: Record<DomainTaskStatus, string> = {
  queued: '排队中',
  running: '计算中',
  succeeded: '已完成',
  cancelling: '取消中',
  cancelled: '已取消',
  retry_wait: '等待重试',
  failed: '失败'
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return '—'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false
  }).format(parsed)
}

export function compactHash(value: string | null | undefined): string {
  if (!value) return '—'
  return value.length > 16 ? `${value.slice(0, 8)}…${value.slice(-6)}` : value
}

export function getErrorMessage(error: unknown, fallback: string): string {
  if (!(error instanceof Error)) return fallback
  return error.message || fallback
}

export function isFeatureDisabled(error: unknown): boolean {
  if (!error || typeof error !== 'object') return false
  const response = (error as { response?: { data?: unknown } }).response
  const detail = response?.data && typeof response.data === 'object'
    ? (response.data as { detail?: unknown }).detail
    : undefined
  return Boolean(
    detail &&
    typeof detail === 'object' &&
    (detail as { code?: string }).code === 'FACTOR_FEATURE_DISABLED'
  )
}
