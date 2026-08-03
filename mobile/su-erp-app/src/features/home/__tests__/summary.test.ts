import type { Invoice } from '@api-types/index';

import { pendingTotal, unreadCount } from '../summary';

function invoice(amount: string, status: Invoice['status']): Invoice {
  return {
    id: Math.random().toString(),
    student_user_code: 'MOB-1',
    amount,
    purpose: 'Hostel',
    status,
    created_at: '2026-08-01T00:00:00Z',
  };
}

test('dues count only pending invoices', () => {
  const rows = [invoice('1500.00', 'pending'), invoice('900.00', 'paid')];

  expect(pendingTotal(rows)).toBe(1500);
});

test('dues sum the decimal strings without string concatenation', () => {
  const rows = [invoice('1500.50', 'pending'), invoice('2000.25', 'pending')];

  expect(pendingTotal(rows)).toBeCloseTo(3500.75, 2);
});

test('no invoices means nothing owed', () => {
  expect(pendingTotal([])).toBe(0);
});

test('cancelled and failed invoices are not owed', () => {
  const rows = [invoice('500.00', 'cancelled'), invoice('700.00', 'failed')];

  expect(pendingTotal(rows)).toBe(0);
});

test('unread counts only unread rows', () => {
  expect(unreadCount([{ read: false }, { read: true }, { read: false }])).toBe(2);
});
