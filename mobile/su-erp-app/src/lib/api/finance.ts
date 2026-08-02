import type { Invoice, Paginated } from '@api-types/index';

import { useConnectivity } from '../net/connectivity';
import { request } from './client';

/** Raised instead of queueing, for mutations that must never fire late. */
export class OfflineError extends Error {
  constructor(message = 'You are offline. Connect to the network and try again.') {
    super(message);
    this.name = 'OfflineError';
  }
}

function uuidv4(): string {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

/**
 * One key per invoice, held for the life of the process.
 *
 * A fresh key per attempt would defeat the point: the backend deduplicates on
 * (invoice, idempotency_key), so a student who taps Pay again after a timeout
 * — the exact case idempotency exists for — would send a new key and be
 * charged twice. Reusing the key means the retry returns the first payment's
 * outcome instead.
 */
const keys = new Map<string, string>();

function idempotencyKeyFor(invoiceId: string): string {
  const existing = keys.get(invoiceId);
  if (existing) return existing;

  const key = uuidv4();
  keys.set(invoiceId, key);
  return key;
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
      idempotency_key: idempotencyKeyFor(invoiceId),
    }),
  });
}

/** Drops a settled invoice's key so a later, genuinely new payment is distinct. */
export function forgetIdempotencyKey(invoiceId: string): void {
  keys.delete(invoiceId);
}
