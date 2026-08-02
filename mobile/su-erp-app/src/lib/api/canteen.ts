import type { CartLine, MenuItem, Order, Paginated } from '@api-types/index';

import { useConnectivity } from '../net/connectivity';
import { request } from './client';
import { OfflineError } from './finance';

export function fetchMenu(): Promise<Paginated<MenuItem>> {
  return request<Paginated<MenuItem>>('/api/v1/menu-items/');
}

export function fetchOrders(): Promise<Paginated<Order>> {
  return request<Paginated<Order>>('/api/v1/orders/');
}

/** Money changes hands here, so this never queues — same rule as payInvoice. */
export async function placeOrder(items: CartLine[]): Promise<Order> {
  if (!useConnectivity.getState().online) throw new OfflineError();

  return request<Order>('/api/v1/orders/', {
    method: 'POST',
    body: JSON.stringify({ items }),
  });
}
