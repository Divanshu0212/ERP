import type { Notification, Paginated } from '@api-types/index';

import { request } from './client';

export function fetchInbox(page?: number): Promise<Paginated<Notification>> {
  const suffix = page ? `?page=${page}` : '';
  return request<Paginated<Notification>>(`/api/v1/notify/inbox${suffix}`);
}

export function markRead(id: string): Promise<void> {
  return request<void>(`/api/v1/notify/inbox/${id}/read`, { method: 'POST' });
}
