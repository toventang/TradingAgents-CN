import axios from 'axios';
import { RiskEvaluationResult, RiskAuditLog } from '../types/risk';

export const checkPreTradeRisk = async (payload: any): Promise<{ evaluation: RiskEvaluationResult; is_blocked: boolean; blocked_orders: any[]; approved_orders: any[] }> => {
  const response = await axios.post('/api/risk/pre-trade/check', payload);
  return response.data;
};

export const listRiskAuditLogs = async (limit = 50, offset = 0): Promise<RiskAuditLog[]> => {
  const response = await axios.get('/api/risk/audit-logs', { params: { limit, offset } });
  return response.data;
};
