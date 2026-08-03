import type { DeviceSummary, LoginRequest, MeResponse, TokenPair } from '@api-types/index';

import { clearRefreshToken, readRefreshToken, saveRefreshToken } from '../auth/storage';
import { request, setAccessToken } from './client';

export async function login(body: LoginRequest): Promise<TokenPair> {
  const tokens = await request<TokenPair>('/api/v1/auth/login', {
    method: 'POST',
    body: JSON.stringify(body),
  });
  setAccessToken(tokens.access);
  await saveRefreshToken(tokens.refresh);
  return tokens;
}

export async function logout(): Promise<void> {
  const refresh = await readRefreshToken();
  if (refresh) {
    // Best-effort: a failed logout call must still clear local credentials,
    // otherwise a network blip leaves the user stuck signed in.
    try {
      await request('/api/v1/auth/logout', {
        method: 'POST',
        body: JSON.stringify({ refresh }),
      });
    } catch {
      // intentionally ignored — local cleanup below is what matters
    }
  }
  setAccessToken(null);
  await clearRefreshToken();
}

export function fetchMe(): Promise<MeResponse> {
  return request<MeResponse>('/api/v1/auth/me');
}

export function listDevices(): Promise<DeviceSummary[]> {
  return request<DeviceSummary[]>('/api/v1/auth/devices');
}

export function revokeDevice(deviceId: string): Promise<void> {
  return request<void>(`/api/v1/auth/devices/${deviceId}`, { method: 'DELETE' });
}
