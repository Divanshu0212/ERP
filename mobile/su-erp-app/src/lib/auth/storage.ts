import * as SecureStore from 'expo-secure-store';

/**
 * The refresh token is the only credential written to disk, and it goes to
 * the Keychain/Keystore — never to MMKV or SQLite, which hold cached data
 * only. The access token is deliberately absent here: it lives in memory
 * for its 15-minute life and is re-derived by refreshing.
 */
const REFRESH_TOKEN_KEY = 'suerp.refresh_token';

export async function saveRefreshToken(token: string): Promise<void> {
  await SecureStore.setItemAsync(REFRESH_TOKEN_KEY, token);
}

export async function readRefreshToken(): Promise<string | null> {
  return SecureStore.getItemAsync(REFRESH_TOKEN_KEY);
}

export async function clearRefreshToken(): Promise<void> {
  await SecureStore.deleteItemAsync(REFRESH_TOKEN_KEY);
}
