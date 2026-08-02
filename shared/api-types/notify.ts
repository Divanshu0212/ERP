/** notify/serializers.py NotificationSerializer. */
export interface Notification {
  id: string;
  title: string;
  body: string;
  read: boolean;
  created_at: string;
}
