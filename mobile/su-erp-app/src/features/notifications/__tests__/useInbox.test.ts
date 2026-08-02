import type { Notification, Paginated } from '@api-types/index';

import { applyRead } from '../useInbox';

function page(): Paginated<Notification> {
  return {
    results: [
      { id: 'n1', title: 'Fees due', body: '', read: false, created_at: '2026-08-01T00:00:00Z' },
      { id: 'n2', title: 'Notice', body: '', read: false, created_at: '2026-08-01T00:00:00Z' },
    ],
    count: 2,
    page: 1,
    num_pages: 1,
  };
}

test('marking one row read leaves the others alone', () => {
  const next = applyRead(page(), 'n1');

  expect(next!.results.find((n) => n.id === 'n1')!.read).toBe(true);
  expect(next!.results.find((n) => n.id === 'n2')!.read).toBe(false);
});

test('the original page is not mutated, so rollback can restore it', () => {
  const original = page();

  applyRead(original, 'n1');

  expect(original.results[0].read).toBe(false);
});

test('an unknown id changes nothing', () => {
  const next = applyRead(page(), 'nope');

  expect(next!.results.every((n) => !n.read)).toBe(true);
});

test('an empty cache stays undefined rather than inventing a page', () => {
  expect(applyRead(undefined, 'n1')).toBeUndefined();
});
