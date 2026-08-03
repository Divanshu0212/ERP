import type { Invoice } from '@api-types/index';

/**
 * The home dashboard's derived numbers, kept out of the component so they can
 * be tested directly — getting these wrong shows a student the wrong amount
 * owed, which is the one number on that screen they act on.
 */
export function pendingTotal(invoices: Invoice[]): number {
  return invoices
    .filter((i) => i.status === 'pending')
    .reduce((sum, i) => sum + Number(i.amount), 0);
}

export function unreadCount(rows: { read: boolean }[]): number {
  return rows.filter((n) => !n.read).length;
}
