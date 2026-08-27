export interface ChannelConfig {
  enabled: boolean;
  min_severity: 'info' | 'warning' | 'critical';
  target_address?: string;
}

export interface NotificationPreference {
  user_id: string;
  channels: Record<string, ChannelConfig>;
  events: string[];
}

export interface NotificationLog {
  log_id: string;
  user_id: string;
  event_id: string;
  channel: string;
  status: string;
  attempts: number;
  target_address?: string;
  error_message?: string;
  created_at: string;
}

// 遗留通知模型：用户通知列表项（与后端 NotificationOut 对齐）
export type NotificationType = 'analysis' | 'alert' | 'system';
export type NotificationStatus = 'unread' | 'read';

export interface NotificationItem {
  id: string;
  type: NotificationType;
  title: string;
  content?: string;
  link?: string;
  source?: string;
  status: NotificationStatus;
  created_at: string;
}

export interface NotificationListResponse {
  items: NotificationItem[];
  total?: number;
  page?: number;
  page_size?: number;
}

export interface NotificationUnreadCountResponse {
  count: number;
}
