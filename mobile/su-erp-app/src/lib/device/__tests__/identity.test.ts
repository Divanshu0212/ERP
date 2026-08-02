import { getDeviceId } from '../identity';

/**
 * Named with a `mock` prefix because jest hoists `jest.mock` factories above
 * every other statement in the file — only `mock*` identifiers are allowed to
 * be referenced from inside one.
 */
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

beforeEach(() => mockStore.clear());

test('generates a device id on first call', async () => {
  const id = await getDeviceId();
  expect(id).toMatch(/^[0-9a-f-]{36}$/);
});

test('returns the same device id on every later call', async () => {
  const first = await getDeviceId();
  const second = await getDeviceId();
  expect(second).toBe(first);
});
