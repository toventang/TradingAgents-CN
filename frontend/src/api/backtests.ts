import axios from 'axios';
import { BacktestResult } from '../types/backtest';

export const submitBacktest = async (payload: any): Promise<{ backtest_id: string; status: string }> => {
  const response = await axios.post('/api/backtests', payload);
  return response.data;
};

export const listBacktests = async (): Promise<BacktestResult[]> => {
  const response = await axios.get('/api/backtests');
  return response.data;
};

export const getBacktest = async (backtestId: string): Promise<BacktestResult> => {
  const response = await axios.get(`/api/backtests/${backtestId}`);
  return response.data;
};

export const getBacktestResult = async (backtestId: string): Promise<any> => {
  const response = await axios.get(`/api/backtests/${backtestId}/result`);
  return response.data;
};

export const compareBacktests = async (backtestIds: string[]): Promise<any> => {
  const response = await axios.post('/api/backtests/compare', { backtest_ids: backtestIds });
  return response.data;
};
