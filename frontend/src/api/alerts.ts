import { request } from './request'
import type {
  AlertEvent,
  AlertHealth,
  AlertPage,
  AlertPreviewResult,
  AlertRule,
  AlertRuleDetail,
  AlertValidationResult
} from '@/types/alert'

const id = (value: string) => encodeURIComponent(value)
const body = <T>(value: unknown): T => value as T
const versionHeaders = (version: number) => ({ 'If-Match': `"${version}"` })

export interface AlertEventQuery {
  rule_id?: string
  symbol?: string
  severity?: 'info' | 'warning' | 'critical'
  start_at?: string
  end_at?: string
  page?: number
  page_size?: number
}

export const alertsApi = {
  async createRule(payload: Record<string, unknown>): Promise<AlertRule> {
    return body(await request.post('/api/alerts/rules', payload))
  },

  async listRules(query: {
    enabled?: boolean
    page?: number
    page_size?: number
  } = {}): Promise<AlertPage<AlertRule>> {
    return body(await request.get('/api/alerts/rules', { params: query }))
  },

  async getRule(ruleId: string): Promise<AlertRuleDetail> {
    return body(await request.get(`/api/alerts/rules/${id(ruleId)}`))
  },

  async updateRule(
    ruleId: string,
    version: number,
    payload: Record<string, unknown>
  ): Promise<AlertRule> {
    return body(await request.put(`/api/alerts/rules/${id(ruleId)}`, payload, {
      headers: versionHeaders(version)
    }))
  },

  async enableRule(ruleId: string, version: number): Promise<AlertRule> {
    return body(await request.post(`/api/alerts/rules/${id(ruleId)}/enable`, {}, {
      headers: versionHeaders(version)
    }))
  },

  async disableRule(ruleId: string, version: number): Promise<AlertRule> {
    return body(await request.post(`/api/alerts/rules/${id(ruleId)}/disable`, {}, {
      headers: versionHeaders(version)
    }))
  },

  async deleteRule(ruleId: string, version: number): Promise<{
    rule_id: string
    deleted_at: string
    last_version: number
    events_retained: boolean
  }> {
    return body(await request.delete(`/api/alerts/rules/${id(ruleId)}`, {
      headers: versionHeaders(version)
    }))
  },

  async validate(payload: Record<string, unknown>): Promise<AlertValidationResult> {
    return body(await request.post('/api/alerts/validate', payload))
  },

  async preview(payload: Record<string, unknown>): Promise<AlertPreviewResult> {
    return body(await request.post('/api/alerts/preview', payload))
  },

  async testNotification(ruleId: string): Promise<{
    notification_id: string
    test_event_id: string
    is_test: true
  }> {
    return body(await request.post(`/api/alerts/rules/${id(ruleId)}/test-notification`))
  },

  async listEvents(query: AlertEventQuery = {}): Promise<AlertPage<AlertEvent>> {
    return body(await request.get('/api/alerts/events', { params: query }))
  },

  async acknowledgeEvent(eventId: string): Promise<AlertEvent> {
    return body(await request.post(`/api/alerts/events/${id(eventId)}/ack`))
  },

  async health(): Promise<AlertHealth> {
    return body(await request.get('/api/alerts/health'))
  }
}
