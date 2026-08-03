import type { Decimal, MenuItem, Order, OrderStatus, Paginated } from '@api-types/index';

import { useConnectivity } from '../net/connectivity';
import { enqueue } from '../offline/queue';
import { NetworkError, request } from './client';
import type { Queued } from './warden';

/**
 * The one forward move offered for each state, mirroring the server's
 * _ALLOWED_TRANSITIONS. Keeping this a strict subset means the app never
 * shows a button whose request the server will reject. Cancelling is legal
 * from placed and preparing too, but that is a separate decision, not an
 * advance, so it is not in this table.
 */
export const NEXT_STATUS: Record<OrderStatus, OrderStatus | null> = {
  placed: 'preparing',
  preparing: 'ready',
  ready: 'completed',
  completed: null,
  cancelled: null,
};

export function fetchOrderBoard(): Promise<Paginated<Order>> {
  return request<Paginated<Order>>('/api/v1/orders/');
}

/**
 * Queueable: kitchens sit in basements. If two operators advance the same
 * order, the server's legal-transition guard rejects the loser with a 400
 * and the queue drops it rather than retrying — the state the kitchen
 * actually reached wins.
 */
export async function advanceOrder(id: string, status: OrderStatus): Promise<Order | Queued> {
  const path = `/api/v1/orders/${id}/status/`;

  if (!useConnectivity.getState().online) {
    await enqueue(path, 'PATCH', { status });
    return { queued: true };
  }

  try {
    return await request<Order>(path, { method: 'PATCH', body: JSON.stringify({ status }) });
  } catch (error) {
    // A basement kitchen keeps its bars and loses its route. Queue rather than
    // drop the advance; the server's transition guard still has the last word.
    if (error instanceof NetworkError) {
      await enqueue(path, 'PATCH', { status });
      return { queued: true };
    }
    throw error;
  }
}

export function setItemAvailability(id: string, available: boolean): Promise<MenuItem> {
  return request<MenuItem>(`/api/v1/menu-items/${id}/`, {
    method: 'PATCH',
    body: JSON.stringify({ available }),
  });
}

/** Price stays a string end to end — it is a DRF DecimalField, not a number. */
export function setItemPrice(id: string, price: Decimal): Promise<MenuItem> {
  return request<MenuItem>(`/api/v1/menu-items/${id}/`, {
    method: 'PATCH',
    body: JSON.stringify({ price }),
  });
}
