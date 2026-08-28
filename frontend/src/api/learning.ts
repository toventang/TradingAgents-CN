import { ApiClient } from './request';
import type { TradeAttributionResult, AITradeReview, LearningProposal } from '../types/learning';

export const getTradeAttribution = async (tradeId: string): Promise<TradeAttributionResult> => {
  const res = await ApiClient.get<TradeAttributionResult>(`/api/learning/reviews/${tradeId}/attribution`);
  return res as unknown as TradeAttributionResult;
};

export const getAITradeReview = async (tradeId: string): Promise<AITradeReview> => {
  const res = await ApiClient.get<AITradeReview>(`/api/learning/reviews/${tradeId}/ai-review`);
  return res as unknown as AITradeReview;
};

export const listLearningProposals = async (): Promise<LearningProposal[]> => {
  const res = await ApiClient.get<LearningProposal[]>('/api/learning/proposals');
  return res as unknown as LearningProposal[];
};

export const applyProposalDraft = async (proposalId: string, approvedItems: string[]): Promise<any> => {
  const res = await ApiClient.post<any>(`/api/learning/proposals/${proposalId}/apply-draft`, { approved_items: approvedItems });
  return res as unknown as any;
};
