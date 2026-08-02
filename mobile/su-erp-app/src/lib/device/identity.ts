import * as SecureStore from 'expo-secure-store';
import { Platform } from 'react-native';

/**
 * A stable per-install identifier. The backend binds refresh chains to it
 * (see accounts/token_service.register_device), so it must survive app
 * restarts — hence SecureStore rather than in-memory state.
 */
const DEVICE_ID_KEY = 'suerp.device_id';

function uuidv4(): string {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

export async function getDeviceId(): Promise<string> {
  const existing = await SecureStore.getItemAsync(DEVICE_ID_KEY);
  if (existing) return existing;

  const generated = uuidv4();
  await SecureStore.setItemAsync(DEVICE_ID_KEY, generated);
  return generated;
}

export function getPlatform(): string {
  return Platform.OS;
}

export function getModelName(): string {
  return `${Platform.OS} ${Platform.Version}`;
}
