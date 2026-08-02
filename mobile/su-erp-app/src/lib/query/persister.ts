import AsyncStorage from '@react-native-async-storage/async-storage';
import { createAsyncStoragePersister } from '@tanstack/query-async-storage-persister';
import { QueryClient } from '@tanstack/react-query';

/**
 * Cached server reads, persisted so a cold start in a dead zone still shows
 * the student their dues, allocation, and timetable. This holds DATA ONLY —
 * tokens live in SecureStore (see lib/auth/storage.ts) and never here.
 *
 * AsyncStorage rather than MMKV: MMKV v3+ is built on Nitro modules, which
 * Expo Go does not ship, so every read and write fails there with "the native
 * NitroModules Turbo/Native-Module could not be found" while the app keeps
 * running — persistence silently does nothing, which is worse than not having
 * it. AsyncStorage is bundled with Expo Go and is fast enough for a cache
 * this size. Revisit if we ever ship a custom dev build.
 */
const CACHE_KEY = 'suerp.query-cache.v1';

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      staleTime: 30_000,
      gcTime: 1000 * 60 * 60 * 24 * 7,
    },
  },
});

export const persister = createAsyncStoragePersister({
  storage: AsyncStorage,
  key: CACHE_KEY,
});

/** When this key's data was last written — drives the offline banner stamp. */
export function cacheAge(queryKey: unknown[]): number | undefined {
  const state = queryClient.getQueryState(queryKey);
  return state?.dataUpdatedAt || undefined;
}

/**
 * Drops cached reads from memory AND from disk. Clearing only the query
 * client would leave the serialized blob on disk, so the next launch would
 * rehydrate the previous user's data.
 */
export async function clearPersistedCache(): Promise<void> {
  queryClient.clear();
  await AsyncStorage.removeItem(CACHE_KEY);
}
