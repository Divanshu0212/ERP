import * as Device from 'expo-device';

import { request } from '@/lib/api/client';

/**
 * Registers this device for push. Called after login, when there is a
 * session to attach the token to. Failure is non-fatal — the in-app inbox
 * still works, so a denied permission must not block sign-in.
 *
 * `expo-notifications` is imported lazily, for two reasons: importing it runs
 * a device-token auto-registration side effect at module load, and in Expo Go
 * it warns that remote push is unsupported (SDK 53 removed Android push from
 * Expo Go). Loading it only at the point of use keeps that out of app launch
 * and out of every test that happens to touch the session store.
 */
export async function registerPushToken(): Promise<void> {
  // An emulator cannot receive a push token; asking would only throw.
  if (!Device.isDevice) return;

  try {
    const Notifications = await import('expo-notifications');

    const existing = await Notifications.getPermissionsAsync();
    const status =
      existing.status === 'granted'
        ? existing.status
        : (await Notifications.requestPermissionsAsync()).status;

    if (status !== 'granted') return;

    const token = (await Notifications.getExpoPushTokenAsync()).data;

    await request('/api/v1/notify/devices', {
      method: 'POST',
      body: JSON.stringify({ push_token: token }),
    });
  } catch {
    // Non-fatal: the inbox is the source of truth.
  }
}
