import { ApiClient } from './request';
import type { BacktestResult } from '../types/backtest';

export const submitBacktest = async (payload: any): Promise<{ backtest_id: string; status: string }> => {
  const res = await ApiClient.post<{ backtest_id: string; status: string }>('/api/backtests', payload);
  return res as unknown as { backtest_id: string; status: string };
};

export const listBacktests = async (): Promise<BacktestResult[]> => {
  const res = await ApiClient.get<BacktestResult[]>('/api/backtests');
  return res as unknown as BacktestResult[];
};

export const getBacktest = async (backtestId: string): Promise<BacktestResult> => {
  const res = await ApiClient.get<BacktestResult>(`/api/backtests/${backtestId}`);
  return res as unknown as BacktestResult;
};

export const getBacktestResult = async (backtestId: string): Promise<any> => {
  const res = await ApiClient.get<any>(`/api/backtests/${backtestId}/result`);
  return res as unknown as any;
};

export const compareBacktests = async (backtestIds: string[]): Promise<any> => {
  const res = await ApiClient.post<any>('/api/backtests/compare', { backtest_ids: backtestIds });
  return res as unknown as any;
};
