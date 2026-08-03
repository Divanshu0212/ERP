import { ApiError, request, setAccessToken } from '../client';

/** `mock`-prefixed so the hoisted jest.mock factory below may reference it. */
const mockStore = new Map<string, string>();

jest.mock('expo-secure-store', () => ({
  getItemAsync: jest.fn(async (k: string) => mockStore.get(k) ?? null),
  setItemAsync: jest.fn(async (k: string, v: string) => {
    mockStore.set(k, v);
  }),
  deleteItemAsync: jest.fn(async (k: string) => {
    mockStore.delete(k);
  }),
}));

/**
 * Pinned so the endpoint probe does not issue its own `/health` fetch here —
 * that would consume the `mockResolvedValueOnce` queued for the request under
 * test and shift every `mock.calls[0]` assertion. Probing has its own tests in
 * endpoint.test.ts.
 */
jest.mock('../endpoint', () => ({
  currentBaseUrl: () => 'http://localhost:8080',
  resolveBaseUrl: async () => 'http://localhost:8080',
  invalidateBaseUrl: jest.fn(),
}));

function envelope(data: unknown, ok = true) {
  return {
    ok: true,
    status: 200,
    json: async () => ({ success: ok, data, message: '', errors: null }),
  };
}

beforeEach(() => {
  mockStore.clear();
  setAccessToken(null);
  global.fetch = jest.fn();
});

test('unwraps the envelope and returns data', async () => {
  (global.fetch as jest.Mock).mockResolvedValueOnce(envelope({ user_code: 'STU-001' }));

  const result = await request<{ user_code: string }>('/api/v1/auth/me');

  expect(result.user_code).toBe('STU-001');
});

test('sends the bearer token when one is set', async () => {
  setAccessToken('access-1');
  (global.fetch as jest.Mock).mockResolvedValueOnce(envelope({}));

  await request('/api/v1/auth/me');

  const headers = (global.fetch as jest.Mock).mock.calls[0][1].headers;
  expect(headers.Authorization).toBe('Bearer access-1');
});

test('sends an X-Request-Id on every call', async () => {
  (global.fetch as jest.Mock).mockResolvedValueOnce(envelope({}));

  await request('/api/v1/auth/me');

  const headers = (global.fetch as jest.Mock).mock.calls[0][1].headers;
  expect(headers['X-Request-Id']).toMatch(/^[0-9a-f-]{36}$/);
});

test('refreshes once and retries after a 401', async () => {
  mockStore.set('suerp.refresh_token', 'refresh-1');
  setAccessToken('expired');
  (global.fetch as jest.Mock)
    .mockResolvedValueOnce({ ok: false, status: 401, json: async () => ({}) })
    .mockResolvedValueOnce(envelope({ access: 'access-2', refresh: 'refresh-2' }))
    .mockResolvedValueOnce(envelope({ user_code: 'STU-001' }));

  const result = await request<{ user_code: string }>('/api/v1/auth/me');

  expect(result.user_code).toBe('STU-001');
  expect((global.fetch as jest.Mock).mock.calls).toHaveLength(3);
});

test('a second 401 clears the session and throws', async () => {
  mockStore.set('suerp.refresh_token', 'refresh-1');
  setAccessToken('expired');
  (global.fetch as jest.Mock)
    .mockResolvedValueOnce({ ok: false, status: 401, json: async () => ({}) })
    .mockResolvedValueOnce({ ok: false, status: 401, json: async () => ({}) });

  await expect(request('/api/v1/auth/me')).rejects.toBeInstanceOf(ApiError);
  expect(mockStore.has('suerp.refresh_token')).toBe(false);
});

test('sends the idempotency key when given one', async () => {
  (global.fetch as jest.Mock).mockResolvedValueOnce(envelope({}));

  await request('/api/v1/grievance/tickets', {
    method: 'POST',
    idempotencyKey: 'key-1',
  });

  const headers = (global.fetch as jest.Mock).mock.calls[0][1].headers;
  expect(headers['Idempotency-Key']).toBe('key-1');
});
