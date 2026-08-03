import type { Invoice, Paginated, RazorpayOrder, RazorpayProof } from '@api-types/index';

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
 * Opens a Razorpay order for an invoice so the checkout widget has something
 * to charge against. 400s when the server has no Razorpay credentials, which
 * the caller treats as "fall through to the simulated gateway".
 */
export async function createInvoiceOrder(invoiceId: string): Promise<RazorpayOrder> {
  if (!useConnectivity.getState().online) throw new OfflineError();

  return request<RazorpayOrder>(`/api/v1/finance/invoices/${invoiceId}/razorpay-order`, {
    method: 'POST',
  });
}

/**
 * Deliberately NOT queueable. A fee payment that silently fires an hour after
 * the student walked away is worse than one that fails in front of them.
 *
 * The Razorpay proof is optional: with it the server verifies the signature
 * against the key secret before marking the invoice paid; without it the
 * server falls through to its simulated gateway. Either way the decision is
 * the server's — this device never decides that a payment succeeded.
 */
export async function payInvoice(invoiceId: string, proof?: RazorpayProof): Promise<void> {
  if (!useConnectivity.getState().online) throw new OfflineError();

  await request<void>('/api/v1/finance/pay', {
    method: 'POST',
    body: JSON.stringify({
      invoice_id: invoiceId,
      idempotency_key: idempotencyKeyFor(`invoice:${invoiceId}`),
      ...(proof ?? {}),
    }),
  });
}

/** Retires a settled invoice's key so a later genuine payment is distinct. */
export function forgetInvoiceKey(invoiceId: string): void {
  forgetIdempotencyKey(`invoice:${invoiceId}`);
}

/** Absolute URL of an invoice's receipt PDF, for opening or sharing. */
export function receiptPdfUrl(invoiceId: string): string {
  return `/api/v1/finance/receipts/by-invoice/${invoiceId}/pdf`;
}
