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
import { NetworkError, request } from './client';

/** Marker returned when a mutation was held for replay rather than sent. */
export type Queued = { queued: true };

function offline(): boolean {
  return !useConnectivity.getState().online;
}

/**
 * Send, and fall back to the queue if the server turns out to be unreachable.
 *
 * The NetInfo check alone is not enough: a phone reports "online" whenever the
 * radio is up, which inside a hostel block is routinely true while nothing can
 * actually reach the gateway. Without this second chance the request fails and
 * the entry is simply lost, even though it is a mutation we are willing to
 * replay. An HTTP error is left alone — the server answered, and the queue
 * must not retry a request it already rejected.
 */
async function sendOrQueue<T>(
  path: string,
  method: string,
  body: unknown,
  send: () => Promise<T>,
): Promise<T | Queued> {
  if (offline()) {
    await enqueue(path, method, body);
    return { queued: true };
  }

  try {
    return await send();
  } catch (error) {
    if (error instanceof NetworkError) {
      await enqueue(path, method, body);
      return { queued: true };
    }
    throw error;
  }
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
  const path = `/api/v1/grievance/${id}/status`;

  return sendOrQueue(path, 'PATCH', { status }, () =>
    request<Ticket>(path, { method: 'PATCH', body: JSON.stringify({ status }) }),
  );
}

export function fetchVisitors(all = false): Promise<Paginated<VisitorLog>> {
  return request<Paginated<VisitorLog>>(`/api/v1/hostel/visitors${all ? '?all=true' : ''}`);
}

/** Queueable: the gate is the single worst-signal spot on most campuses. */
export async function logVisitor(input: VisitorInput): Promise<VisitorLog | Queued> {
  return sendOrQueue('/api/v1/hostel/visitors', 'POST', input, () =>
    request<VisitorLog>('/api/v1/hostel/visitors', {
      method: 'POST',
      body: JSON.stringify(input),
    }),
  );
}

export async function checkoutVisitor(id: string): Promise<VisitorLog | Queued> {
  const path = `/api/v1/hostel/visitors/${id}/checkout`;

  return sendOrQueue(path, 'POST', {}, () => request<VisitorLog>(path, { method: 'POST' }));
}
