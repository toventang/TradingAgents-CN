import axios from 'axios';
import { Campaign } from '../types/campaign';

export const listCampaigns = async (): Promise<Campaign[]> => {
  const response = await axios.get('/api/campaigns');
  return response.data;
};

export const getCampaign = async (campaignId: string): Promise<Campaign> => {
  const response = await axios.get(`/api/campaigns/${campaignId}`);
  return response.data;
};

export const createCampaign = async (payload: any): Promise<{ campaign: Campaign }> => {
  const response = await axios.post('/api/campaigns', payload);
  return response.data;
};

export const activateCampaign = async (campaignId: string): Promise<Campaign> => {
  const response = await axios.post(`/api/campaigns/${campaignId}/activate`);
  return response.data;
};

export const pauseCampaign = async (campaignId: string): Promise<Campaign> => {
  const response = await axios.post(`/api/campaigns/${campaignId}/pause`);
  return response.data;
};

export const resumeCampaign = async (campaignId: string, note = ''): Promise<Campaign> => {
  const response = await axios.post(`/api/campaigns/${campaignId}/resume`, { confirmation_note: note });
  return response.data;
};

export const stopCampaign = async (campaignId: string): Promise<Campaign> => {
  const response = await axios.post(`/api/campaigns/${campaignId}/stop`);
  return response.data;
};

export const getCampaignPerformance = async (campaignId: string): Promise<any> => {
  const response = await axios.get(`/api/campaigns/${campaignId}/performance`);
  return response.data;
};
