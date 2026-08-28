import { ApiClient } from './request';
import type { RiskEvaluationResult, RiskAuditLog } from '../types/risk';

export const checkPreTradeRisk = async (payload: any): Promise<{ evaluation: RiskEvaluationResult; is_blocked: boolean; blocked_orders: any[]; approved_orders: any[] }> => {
  const res = await ApiClient.post<{ evaluation: RiskEvaluationResult; is_blocked: boolean; blocked_orders: any[]; approved_orders: any[] }>('/api/risk/pre-trade/check', payload);
  return res as unknown as { evaluation: RiskEvaluationResult; is_blocked: boolean; blocked_orders: any[]; approved_orders: any[] };
};

export const listRiskAuditLogs = async (limit = 50, offset = 0): Promise<RiskAuditLog[]> => {
  const res = await ApiClient.get<RiskAuditLog[]>('/api/risk/audit-logs', { limit, offset });
  return res as unknown as RiskAuditLog[];
};
