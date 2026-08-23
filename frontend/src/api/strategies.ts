import axios from 'axios';
import { Strategy, StrategyVersion } from '../types/strategy';

export const listStrategies = async (includeSystem = true): Promise<Strategy[]> => {
  const response = await axios.get('/api/strategies', { params: { include_system: includeSystem } });
  return response.data;
};

export const getStrategy = async (strategyId: string): Promise<{ strategy: Strategy; versions: StrategyVersion[] }> => {
  const response = await axios.get(`/api/strategies/${strategyId}`);
  return response.data;
};

export const createStrategy = async (payload: any): Promise<{ strategy: Strategy; version: StrategyVersion }> => {
  const response = await axios.post('/api/strategies', payload);
  return response.data;
};

export const publishVersion = async (strategyId: string, payload: any): Promise<StrategyVersion> => {
  const response = await axios.post(`/api/strategies/${strategyId}/publish`, payload);
  return response.data;
};

export const cloneStrategy = async (strategyId: string, payload: any): Promise<{ strategy: Strategy; version: StrategyVersion }> => {
  const response = await axios.post(`/api/strategies/${strategyId}/clone`, payload);
  return response.data;
};

export const evaluateSignals = async (payload: any): Promise<any[]> => {
  const response = await axios.post('/api/strategies/signals/evaluate', payload);
  return response.data;
};

export const diffVersions = async (strategyId: string, v1: number, v2: number): Promise<any> => {
  const response = await axios.get(`/api/strategies/${strategyId}/diff`, { params: { v1, v2 } });
  return response.data;
};

export const rollbackVersion = async (strategyId: string, targetVersionNum: number, commitMessage?: string): Promise<StrategyVersion> => {
  const response = await axios.post(`/api/strategies/${strategyId}/rollback`, {
    target_version_num: targetVersionNum,
    commit_message: commitMessage
  });
  return response.data;
};
