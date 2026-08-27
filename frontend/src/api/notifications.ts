import axios from 'axios';
import { ApiClient, type ApiResponse } from './request';
import type {
  NotificationPreference,
  NotificationLog,
  NotificationListResponse,
  NotificationUnreadCountResponse
} from '../types/notification';

// 重新导出 NotificationItem，方便调用方按 `import { type NotificationItem } from '@/api/notifications'` 使用
export type { NotificationItem } from '../types/notification';

// ============ 偏好与分发日志（旧接口） ============

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

// ============ 用户通知列表 / 已读（store 使用） ============
//
// 这里返回 `ApiResponse<T>` 形态（{ success, data, message, ... }），
// 与 src/stores/notifications.ts 中 `res?.data?.count` / `res?.data?.items` 的访问方式保持一致。
// 所有方法在 store 中均被 try/catch 包裹，即便后端尚未提供对应端点，也不会阻断前端运行。

export interface NotificationListQuery {
  status?: 'unread' | 'all' | 'read';
  type?: 'analysis' | 'alert' | 'system';
  page?: number;
  page_size?: number;
}

export const notificationsApi = {
  /** 获取未读通知数量 */
  getUnreadCount(): Promise<ApiResponse<NotificationUnreadCountResponse>> {
    return ApiClient.get<NotificationUnreadCountResponse>('/api/notifications/unread_count');
  },

  /** 获取通知列表 */
  getList(params: NotificationListQuery = {}): Promise<ApiResponse<NotificationListResponse>> {
    return ApiClient.get<NotificationListResponse>('/api/notifications', params);
  },

  /** 标记单条通知为已读 */
  markRead(id: string): Promise<ApiResponse<{ success: boolean }>> {
    return ApiClient.post<{ success: boolean }>(`/api/notifications/${id}/read`);
  },

  /** 标记全部通知为已读 */
  markAllRead(): Promise<ApiResponse<{ success: boolean; modified?: number }>> {
    return ApiClient.post<{ success: boolean; modified?: number }>('/api/notifications/read-all');
  }
};
