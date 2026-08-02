import type { MeResponse, Role } from '@api-types/index';
import { create } from 'zustand';

import { fetchMe, login as apiLogin, logout as apiLogout } from '../api/auth';
import { refreshSession, setAccessToken } from '../api/client';
import { getDeviceId, getModelName, getPlatform } from '../device/identity';
import { readRefreshToken } from './storage';

/** Roles the app supports. Everyone else is directed to the web portal. */
const ROLE_HOMES: Partial<Record<Role, string>> = {
  student: '/(student)',
  warden: '/(warden)',
  driver: '/(driver)',
  canteen_owner: '/(canteen-owner)',
};

export function roleHome(role: Role): string {
  return ROLE_HOMES[role] ?? '/unsupported-role';
}

interface SessionState {
  status: 'loading' | 'signed-out' | 'signed-in';
  user: MeResponse | null;
  signIn(institutionSlug: string, email: string, password: string): Promise<void>;
  signOut(): Promise<void>;
  restore(): Promise<void>;
}

export const useSession = create<SessionState>((set) => ({
  status: 'loading',
  user: null,

  async signIn(institutionSlug, email, password) {
    await apiLogin({
      institution_slug: institutionSlug,
      email,
      password,
      device_id: await getDeviceId(),
      platform: getPlatform(),
      model_name: getModelName(),
    });
    set({ user: await fetchMe(), status: 'signed-in' });
  },

  async signOut() {
    await apiLogout();
    set({ user: null, status: 'signed-out' });
  },

  /**
   * Cold start: the access token died with the last process, so the stored
   * refresh token is the only way back in. A rejected refresh means the
   * device was revoked or the chain was reused — sign out rather than retry.
   */
  async restore() {
    const refresh = await readRefreshToken();
    if (!refresh) {
      set({ status: 'signed-out', user: null });
      return;
    }

    try {
      await refreshSession();
      set({ user: await fetchMe(), status: 'signed-in' });
    } catch {
      setAccessToken(null);
      set({ status: 'signed-out', user: null });
    }
  },
}));
