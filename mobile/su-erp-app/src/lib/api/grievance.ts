import type { Paginated, Ticket, TicketInput } from '@api-types/index';

import { useConnectivity } from '../net/connectivity';
import { enqueue } from '../offline/queue';
import { request } from './client';

export function fetchTickets(): Promise<Paginated<Ticket>> {
  return request<Paginated<Ticket>>('/api/v1/grievance');
}

/**
 * The one student mutation that queues. Hostel blocks are exactly where
 * complaints get raised and exactly where the signal dies, so a grievance
 * filed offline is held and replayed rather than lost. Unlike a payment or a
 * seat, a complaint landing twenty minutes late is harmless.
 */
export async function createTicket(input: TicketInput): Promise<Ticket | { queued: true }> {
  if (!useConnectivity.getState().online) {
    await enqueue('/api/v1/grievance', 'POST', input);
    return { queued: true };
  }

  return request<Ticket>('/api/v1/grievance', {
    method: 'POST',
    body: JSON.stringify(input),
  });
}
