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
