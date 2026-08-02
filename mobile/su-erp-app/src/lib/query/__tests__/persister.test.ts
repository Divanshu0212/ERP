import { cacheAge, clearPersistedCache, queryClient } from '../persister';

jest.mock('@react-native-async-storage/async-storage', () => {
  const store = new Map<string, string>();
  return {
    __esModule: true,
    default: {
      getItem: jest.fn(async (k: string) => store.get(k) ?? null),
      setItem: jest.fn(async (k: string, v: string) => {
        store.set(k, v);
      }),
      removeItem: jest.fn(async (k: string) => {
        store.delete(k);
      }),
    },
  };
});

beforeEach(() => queryClient.clear());

test('cacheAge is undefined for a key that was never fetched', () => {
  expect(cacheAge(['invoices'])).toBeUndefined();
});

test('cacheAge returns the update timestamp once data is cached', () => {
  queryClient.setQueryData(['invoices'], [{ id: '1' }]);
  expect(cacheAge(['invoices'])).toBeGreaterThan(0);
});

test('clearing the cache drops the previous user data from memory and disk', async () => {
  const storage = jest.requireMock('@react-native-async-storage/async-storage').default;
  queryClient.setQueryData(['invoices'], [{ id: '1' }]);

  await clearPersistedCache();

  expect(queryClient.getQueryData(['invoices'])).toBeUndefined();
  expect(storage.removeItem).toHaveBeenCalledWith('suerp.query-cache.v1');
});
