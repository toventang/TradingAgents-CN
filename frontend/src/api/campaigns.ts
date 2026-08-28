import { ApiClient } from './request';
import type { Campaign } from '../types/campaign';

export const listCampaigns = async (): Promise<Campaign[]> => {
  const res = await ApiClient.get<Campaign[]>('/api/campaigns');
  return res as unknown as Campaign[];
};

export const getCampaign = async (campaignId: string): Promise<Campaign> => {
  const res = await ApiClient.get<Campaign>(`/api/campaigns/${campaignId}`);
  return res as unknown as Campaign;
};

export const createCampaign = async (payload: any): Promise<{ campaign: Campaign }> => {
  const res = await ApiClient.post<{ campaign: Campaign }>('/api/campaigns', payload);
  return res as unknown as { campaign: Campaign };
};

export const activateCampaign = async (campaignId: string): Promise<Campaign> => {
  const res = await ApiClient.post<Campaign>(`/api/campaigns/${campaignId}/activate`);
  return res as unknown as Campaign;
};

export const pauseCampaign = async (campaignId: string): Promise<Campaign> => {
  const res = await ApiClient.post<Campaign>(`/api/campaigns/${campaignId}/pause`);
  return res as unknown as Campaign;
};

export const resumeCampaign = async (campaignId: string, note = ''): Promise<Campaign> => {
  const res = await ApiClient.post<Campaign>(`/api/campaigns/${campaignId}/resume`, { confirmation_note: note });
  return res as unknown as Campaign;
};

export const stopCampaign = async (campaignId: string): Promise<Campaign> => {
  const res = await ApiClient.post<Campaign>(`/api/campaigns/${campaignId}/stop`);
  return res as unknown as Campaign;
};

export const getCampaignPerformance = async (campaignId: string): Promise<any> => {
  const res = await ApiClient.get<any>(`/api/campaigns/${campaignId}/performance`);
  return res as unknown as any;
};
