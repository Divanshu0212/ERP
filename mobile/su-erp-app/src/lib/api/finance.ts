import type { Invoice, Paginated } from '@api-types/index';

import { useConnectivity } from '../net/connectivity';
import { request } from './client';
import { forgetIdempotencyKey, idempotencyKeyFor } from './idempotency';

/** Raised instead of queueing, for mutations that must never fire late. */
export class OfflineError extends Error {
  constructor(message = 'You are offline. Connect to the network and try again.') {
    super(message);
    this.name = 'OfflineError';
  }
}

export function fetchInvoices(): Promise<Paginated<Invoice>> {
  return request<Paginated<Invoice>>('/api/v1/finance/invoices');
}

/**
 * Deliberately NOT queueable. A fee payment that silently fires an hour after
 * the student walked away is worse than one that fails in front of them —
 * see the spec's offline rules.
 */
export async function payInvoice(invoiceId: string): Promise<void> {
  if (!useConnectivity.getState().online) throw new OfflineError();

  await request<void>('/api/v1/finance/pay', {
    method: 'POST',
    body: JSON.stringify({
      invoice_id: invoiceId,
      idempotency_key: idempotencyKeyFor(`invoice:${invoiceId}`),
    }),
  });
}

/** Retires a settled invoice's key so a later genuine payment is distinct. */
export function forgetInvoiceKey(invoiceId: string): void {
  forgetIdempotencyKey(`invoice:${invoiceId}`);
}
