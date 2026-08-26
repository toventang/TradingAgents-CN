import axios from 'axios';
import { TradeAttributionResult, AITradeReview, LearningProposal } from '../types/learning';

export const getTradeAttribution = async (tradeId: string): Promise<TradeAttributionResult> => {
  const response = await axios.get(`/api/learning/reviews/${tradeId}/attribution`);
  return response.data;
};

export const getAITradeReview = async (tradeId: string): Promise<AITradeReview> => {
  const response = await axios.get(`/api/learning/reviews/${tradeId}/ai-review`);
  return response.data;
};

export const listLearningProposals = async (): Promise<LearningProposal[]> => {
  const response = await axios.get('/api/learning/proposals');
  return response.data;
};

export const applyProposalDraft = async (proposalId: string, approvedItems: string[]): Promise<any> => {
  const response = await axios.post(`/api/learning/proposals/${proposalId}/apply-draft`, { approved_items: approvedItems });
  return response.data;
};
