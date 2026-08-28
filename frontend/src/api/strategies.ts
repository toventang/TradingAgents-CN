import { ApiClient } from './request';
import type { Strategy, StrategyVersion } from '../types/strategy';

export const listStrategies = async (includeSystem = true): Promise<Strategy[]> => {
  const res = await ApiClient.get<Strategy[]>('/api/strategies', { include_system: includeSystem });
  return res as unknown as Strategy[];
};

export const getStrategy = async (strategyId: string): Promise<{ strategy: Strategy; versions: StrategyVersion[] }> => {
  const res = await ApiClient.get<{ strategy: Strategy; versions: StrategyVersion[] }>(`/api/strategies/${strategyId}`);
  return res as unknown as { strategy: Strategy; versions: StrategyVersion[] };
};

export const createStrategy = async (payload: any): Promise<{ strategy: Strategy; version: StrategyVersion }> => {
  const res = await ApiClient.post<{ strategy: Strategy; version: StrategyVersion }>('/api/strategies', payload);
  return res as unknown as { strategy: Strategy; version: StrategyVersion };
};

export const publishVersion = async (strategyId: string, payload: any): Promise<StrategyVersion> => {
  const res = await ApiClient.post<StrategyVersion>(`/api/strategies/${strategyId}/publish`, payload);
  return res as unknown as StrategyVersion;
};

export const cloneStrategy = async (strategyId: string, payload: any): Promise<{ strategy: Strategy; version: StrategyVersion }> => {
  const res = await ApiClient.post<{ strategy: Strategy; version: StrategyVersion }>(`/api/strategies/${strategyId}/clone`, payload);
  return res as unknown as { strategy: Strategy; version: StrategyVersion };
};

export const evaluateSignals = async (payload: any): Promise<any[]> => {
  const res = await ApiClient.post<any[]>('/api/strategies/signals/evaluate', payload);
  return res as unknown as any[];
};

export const diffVersions = async (strategyId: string, v1: number, v2: number): Promise<any> => {
  const res = await ApiClient.get<any>(`/api/strategies/${strategyId}/diff`, { v1, v2 });
  return res as unknown as any;
};

export const rollbackVersion = async (strategyId: string, targetVersionNum: number, commitMessage?: string): Promise<StrategyVersion> => {
  const res = await ApiClient.post<StrategyVersion>(`/api/strategies/${strategyId}/rollback`, {
    target_version_num: targetVersionNum,
    commit_message: commitMessage
  });
  return res as unknown as StrategyVersion;
};
