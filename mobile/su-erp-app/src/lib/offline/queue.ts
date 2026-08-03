import { ApiError, request } from '../api/client';

/**
 * Field-ops mutations captured offline and replayed on reconnect.
 *
 * Only mutations that genuinely happen in dead zones belong here — marking
 * attendance, advancing an order, scanning a pass, logging a visitor, filing
 * a grievance, batching GPS breadcrumbs. Payments deliberately do NOT queue:
 * a fee payment that silently fires an hour later is worse than one that
 * fails loudly now.
 *
 * `id` is generated at capture time and travels as the Idempotency-Key, so a
 * double replay is a no-op on the server side.
 */
export const MAX_ATTEMPTS = 5;

/** Server rejections that mean "this will never succeed" — drop, never retry. */
const TERMINAL_STATUSES = [400, 403, 404, 409, 422];

export interface QueuedMutation {
  id: string;
  endpoint: string;
  method: string;
  body: string;
  attempts: number;
  createdAt: number;
  status: 'pending' | 'failed';
}

export interface QueueStore {
  insert(row: QueuedMutation): Promise<void>;
  all(): Promise<QueuedMutation[]>;
  update(row: QueuedMutation): Promise<void>;
  remove(id: string): Promise<void>;
}

export function createMemoryStore(): QueueStore {
  let rows: QueuedMutation[] = [];
  return {
    async insert(row) {
      rows.push(row);
    },
    async all() {
      return [...rows];
    },
    async update(row) {
      rows = rows.map((r) => (r.id === row.id ? row : r));
    },
    async remove(id) {
      rows = rows.filter((r) => r.id !== id);
    },
  };
}

let store: QueueStore = createMemoryStore();

export function setStore(next: QueueStore): void {
  store = next;
}

function uuidv4(): string {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

export async function enqueue(
  endpoint: string,
  method: string,
  body: unknown,
): Promise<QueuedMutation> {
  const row: QueuedMutation = {
    id: uuidv4(),
    endpoint,
    method,
    body: JSON.stringify(body),
    attempts: 0,
    createdAt: Date.now(),
    status: 'pending',
  };
  await store.insert(row);
  return row;
}

export function list(): Promise<QueuedMutation[]> {
  return store.all();
}

export function discard(id: string): Promise<void> {
  return store.remove(id);
}

export async function replay(): Promise<{ sent: number; dropped: number; failed: number }> {
  const rows = (await store.all())
    .filter((r) => r.status === 'pending')
    .sort((a, b) => a.createdAt - b.createdAt);

  let sent = 0;
  let dropped = 0;
  let failed = 0;

  for (const row of rows) {
    try {
      await request(row.endpoint, {
        method: row.method,
        body: row.body,
        idempotencyKey: row.id,
      });
      await store.remove(row.id);
      sent += 1;
    } catch (error) {
      const status = error instanceof ApiError ? error.status : 0;

      if (TERMINAL_STATUSES.includes(status)) {
        // The server has ruled on this: someone else advanced the order, the
        // ticket vanished, the payload is bad. Retrying cannot change that.
        await store.remove(row.id);
        dropped += 1;
        continue;
      }

      const attempts = row.attempts + 1;
      const next: QueuedMutation = {
        ...row,
        attempts,
        status: attempts >= MAX_ATTEMPTS ? 'failed' : 'pending',
      };
      await store.update(next);
      if (next.status === 'failed') failed += 1;
    }
  }

  return { sent, dropped, failed };
}
