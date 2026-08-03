import {
  CANDIDATES,
  currentBaseUrl,
  invalidateBaseUrl,
  resetEndpointForTests,
  resolveBaseUrl,
} from '../endpoint';

const TUNNEL = 'https://tunnel.example.com';
const LOCAL = 'http://localhost:8080';

function mockReachable(reachable: string[]) {
  (global.fetch as jest.Mock).mockImplementation((url: string) => {
    const origin = CANDIDATES.find((c) => url.startsWith(c));
    if (origin && reachable.includes(origin)) {
      return Promise.resolve({ ok: true, status: 200 } as Response);
    }
    return Promise.reject(new Error('unreachable'));
  });
}

beforeEach(() => {
  global.fetch = jest.fn() as unknown as typeof fetch;
  resetEndpointForTests({ candidates: [TUNNEL, LOCAL] });
});

test('the tunnel wins when both answer', async () => {
  mockReachable([TUNNEL, LOCAL]);

  expect(await resolveBaseUrl()).toBe(TUNNEL);
});

test('localhost is used when the tunnel is down', async () => {
  mockReachable([LOCAL]);

  expect(await resolveBaseUrl()).toBe(LOCAL);
});

test('the last known good URL is reused rather than re-probed', async () => {
  mockReachable([TUNNEL, LOCAL]);
  await resolveBaseUrl();
  (global.fetch as jest.Mock).mockClear();

  await resolveBaseUrl();

  expect(global.fetch).not.toHaveBeenCalled();
});

test('a failed request re-probes and moves to the surviving endpoint', async () => {
  mockReachable([TUNNEL, LOCAL]);
  expect(await resolveBaseUrl()).toBe(TUNNEL);

  // The tunnel dies mid-session, exactly as a quick tunnel does on restart.
  invalidateBaseUrl();
  mockReachable([LOCAL]);

  expect(await resolveBaseUrl()).toBe(LOCAL);
});

test('falls back to the first candidate when nothing answers', async () => {
  mockReachable([]);

  // Offline is not the same as misconfigured: returning a usable URL lets the
  // offline queue capture the mutation instead of throwing at call sites.
  expect(await resolveBaseUrl()).toBe(TUNNEL);
});

test('concurrent callers share one probe', async () => {
  mockReachable([TUNNEL, LOCAL]);

  const [a, b] = await Promise.all([resolveBaseUrl(), resolveBaseUrl()]);

  expect(a).toBe(TUNNEL);
  expect(b).toBe(TUNNEL);
  // One probe per candidate, not two.
  expect((global.fetch as jest.Mock).mock.calls.length).toBeLessThanOrEqual(CANDIDATES.length);
});

test('currentBaseUrl is usable before any probe resolves', () => {
  expect(currentBaseUrl()).toBe(TUNNEL);
});
