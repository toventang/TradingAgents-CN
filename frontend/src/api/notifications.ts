import axios from 'axios';
import { NotificationPreference, NotificationLog } from '../types/notification';

export const getNotificationPreferences = async (): Promise<NotificationPreference> => {
  const response = await axios.get('/api/notifications/preferences');
  return response.data;
};

export const updateNotificationPreferences = async (pref: NotificationPreference): Promise<NotificationPreference> => {
  const response = await axios.put('/api/notifications/preferences', pref);
  return response.data;
};

export const listNotificationLogs = async (): Promise<NotificationLog[]> => {
  const response = await axios.get('/api/notifications/logs');
  return response.data;
};

export const testWebhook = async (targetUrl: string): Promise<any> => {
  const response = await axios.post('/api/notifications/webhooks/test', { target_url: targetUrl });
  return response.data;
};
