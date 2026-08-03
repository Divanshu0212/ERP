import { ApiError } from '../../api/client';
import { MAX_ATTEMPTS, createMemoryStore, enqueue, list, replay, setStore } from '../queue';

jest.mock('../../api/client', () => {
  // Written without a TypeScript parameter property: those desugar to an
  // assignment babel's jest.mock hoisting check reads as an out-of-scope
  // variable access, which fails the whole suite before it runs.
  class MockApiError extends Error {
    status: number;

    constructor(message: string, status: number) {
      super(message);
      this.status = status;
    }
  }
  return { request: jest.fn(), ApiError: MockApiError };
});

const { request } = jest.requireMock('../../api/client');

beforeEach(() => {
  setStore(createMemoryStore());
  request.mockReset();
});

test('enqueued mutations get a uuid idempotency key', async () => {
  const row = await enqueue('/api/v1/attendance/mark', 'POST', { session: 'S1' });
  expect(row.id).toMatch(/^[0-9a-f-]{36}$/);
});

test('replay sends pending mutations and clears them', async () => {
  request.mockResolvedValue({});
  await enqueue('/api/v1/attendance/mark', 'POST', { session: 'S1' });

  const result = await replay();

  expect(result.sent).toBe(1);
  expect(await list()).toHaveLength(0);
});

test('replay sends the row id as the idempotency key', async () => {
  request.mockResolvedValue({});
  const row = await enqueue('/api/v1/attendance/mark', 'POST', { session: 'S1' });

  await replay();

  expect(request).toHaveBeenCalledWith(
    '/api/v1/attendance/mark',
    expect.objectContaining({ idempotencyKey: row.id }),
  );
});

test('replay preserves insertion order', async () => {
  request.mockResolvedValue({});
  await enqueue('/first', 'POST', {});
  await enqueue('/second', 'POST', {});

  await replay();

  expect(request.mock.calls.map((c: unknown[]) => c[0])).toEqual(['/first', '/second']);
});

test('a 409 drops the mutation instead of retrying it', async () => {
  request.mockRejectedValue(new ApiError('Already completed.', 409));
  await enqueue('/api/v1/orders/1/status', 'POST', { status: 'completed' });

  const result = await replay();

  expect(result.dropped).toBe(1);
  expect(await list()).toHaveLength(0);
});

test('a 422 also drops the mutation', async () => {
  request.mockRejectedValue(new ApiError('Unprocessable.', 422));
  await enqueue('/api/v1/orders/1/status', 'POST', { status: 'completed' });

  await replay();

  expect(await list()).toHaveLength(0);
});

test('a 500 keeps the mutation and counts an attempt', async () => {
  request.mockRejectedValue(new ApiError('Server error.', 500));
  await enqueue('/api/v1/attendance/mark', 'POST', {});

  await replay();

  const [row] = await list();
  expect(row.attempts).toBe(1);
  expect(row.status).toBe('pending');
});

test('a mutation is marked failed after the attempt limit', async () => {
  request.mockRejectedValue(new ApiError('Server error.', 500));
  await enqueue('/api/v1/attendance/mark', 'POST', {});

  for (let i = 0; i < MAX_ATTEMPTS; i += 1) await replay();

  const [row] = await list();
  expect(row.attempts).toBe(MAX_ATTEMPTS);
  expect(row.status).toBe('failed');
});

test('failed mutations are skipped by later replays', async () => {
  request.mockRejectedValue(new ApiError('Server error.', 500));
  await enqueue('/api/v1/attendance/mark', 'POST', {});
  for (let i = 0; i < MAX_ATTEMPTS; i += 1) await replay();
  request.mockReset();

  await replay();

  expect(request).not.toHaveBeenCalled();
});
