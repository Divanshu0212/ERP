import { useQuery } from '@tanstack/react-query';

import { request } from '@/lib/api/client';
import { useConnectivity } from '@/lib/net/connectivity';
import { enqueue } from '@/lib/offline/queue';

export const PASS_TOKEN_KEY = ['transport', 'pass-token'];

export interface PassToken {
  token: string;
  expires_in: number;
}

export interface ScanResult {
  accepted: boolean;
  student_user_code: string;
  scanned_at?: string;
}

export type Queued = { queued: true };

export function fetchPassToken(): Promise<PassToken> {
  return request<PassToken>('/api/v1/transport/passes/mine/qr');
}

/**
 * The QR must re-render before its token expires, or the student holds up a
 * dead code. Refetching slightly ahead of the TTL keeps a live code on
 * screen without a visible gap.
 */
export function usePassToken() {
  return useQuery({
    queryKey: PASS_TOKEN_KEY,
    queryFn: fetchPassToken,
    refetchInterval: (query) => ((query.state.data?.expires_in ?? 30) - 5) * 1000,
    staleTime: 0,
    gcTime: 0,
  });
}

/**
 * Queueable: the gate and the moving bus are precisely where signal dies.
 * The server is still the authority on whether a nonce was already spent —
 * a queued scan that turns out to be a replay comes back 409 and the queue
 * drops it, which is the correct outcome.
 */
export async function submitScan(token: string): Promise<ScanResult | Queued> {
  if (!useConnectivity.getState().online) {
    await enqueue('/api/v1/transport/scans', 'POST', { token });
    return { queued: true };
  }

  return request<ScanResult>('/api/v1/transport/scans', {
    method: 'POST',
    body: JSON.stringify({ token }),
  });
}
