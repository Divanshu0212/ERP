import type {
  Allocation,
  Paginated,
  Ticket,
  TicketStatus,
  VisitorInput,
  VisitorLog,
} from '@api-types/index';

import { useConnectivity } from '../net/connectivity';
import { enqueue } from '../offline/queue';
import { request } from './client';

/** Marker returned when a mutation was held for replay rather than sent. */
export type Queued = { queued: true };

function offline(): boolean {
  return !useConnectivity.getState().online;
}

export function fetchEscalatedTickets(): Promise<Paginated<Ticket>> {
  return request<Paginated<Ticket>>('/api/v1/grievance');
}

/**
 * The whole tenant's allocations, which is the warden's roster.
 *
 * Deliberately NOT /allocations/mine: that route is role_required("student")
 * and answers "where do I live", so a warden's token gets a 403 there. The
 * tenant-scoped list is the one its own docstring calls "what a warden needs".
 */
export function fetchBlockRoster(): Promise<Paginated<Allocation>> {
  return request<Paginated<Allocation>>('/api/v1/hostel/allocations?status=confirmed');
}

/**
 * Queueable: a warden closing tickets while walking a block loses signal
 * constantly, and a status change landing a few minutes late costs nothing.
 * The server's legal-transition guard rejects anything that no longer makes
 * sense by the time it arrives, and the queue drops those rather than
 * retrying (409/400 are terminal).
 */
export async function setTicketStatus(id: string, status: TicketStatus): Promise<Ticket | Queued> {
  if (offline()) {
    await enqueue(`/api/v1/grievance/${id}/status`, 'PATCH', { status });
    return { queued: true };
  }

  return request<Ticket>(`/api/v1/grievance/${id}/status`, {
    method: 'PATCH',
    body: JSON.stringify({ status }),
  });
}

export function fetchVisitors(all = false): Promise<Paginated<VisitorLog>> {
  return request<Paginated<VisitorLog>>(`/api/v1/hostel/visitors${all ? '?all=true' : ''}`);
}

/** Queueable: the gate is the single worst-signal spot on most campuses. */
export async function logVisitor(input: VisitorInput): Promise<VisitorLog | Queued> {
  if (offline()) {
    await enqueue('/api/v1/hostel/visitors', 'POST', input);
    return { queued: true };
  }

  return request<VisitorLog>('/api/v1/hostel/visitors', {
    method: 'POST',
    body: JSON.stringify(input),
  });
}

export async function checkoutVisitor(id: string): Promise<VisitorLog | Queued> {
  if (offline()) {
    await enqueue(`/api/v1/hostel/visitors/${id}/checkout`, 'POST', {});
    return { queued: true };
  }

  return request<VisitorLog>(`/api/v1/hostel/visitors/${id}/checkout`, { method: 'POST' });
}
