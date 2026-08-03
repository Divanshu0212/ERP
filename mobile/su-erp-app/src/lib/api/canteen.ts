import type { CartLine, MenuItem, Order, Paginated, RazorpayOrder, RazorpayProof } from '@api-types/index';

import { useConnectivity } from '../net/connectivity';
import { request } from './client';
import { OfflineError } from './finance';

export function fetchMenu(): Promise<Paginated<MenuItem>> {
  return request<Paginated<MenuItem>>('/api/v1/menu-items/');
}

export function fetchOrders(): Promise<Paginated<Order>> {
  return request<Paginated<Order>>('/api/v1/orders/');
}

/**
 * Prices the cart server-side and opens a checkout order. Creates no Order
 * rows — this only produces what the Razorpay widget needs. When Razorpay is
 * unconfigured the server returns a simulated order (SIM- prefixed id, empty
 * key_id) so the flow still works end to end.
 */
export async function checkoutCart(items: CartLine[]): Promise<RazorpayOrder> {
  if (!useConnectivity.getState().online) throw new OfflineError();

  return request<RazorpayOrder>('/api/v1/orders/checkout', {
    method: 'POST',
    body: JSON.stringify({ items }),
  });
}

/**
 * Money changes hands here, so this never queues — same rule as payInvoice.
 * The Razorpay proof is verified server-side before the order is created.
 */
export async function placeOrder(items: CartLine[], proof?: RazorpayProof): Promise<Order> {
  if (!useConnectivity.getState().online) throw new OfflineError();

  return request<Order>('/api/v1/orders/', {
    method: 'POST',
    body: JSON.stringify({ items, ...(proof ?? {}) }),
  });
}

export interface PickupToken {
  token: string;
  expires_in: number;
}

/** Only mints for an order the server considers `ready` — 400 otherwise. */
export function fetchPickupToken(orderId: string): Promise<PickupToken> {
  return request<PickupToken>(`/api/v1/orders/${orderId}/pickup-token`);
}
