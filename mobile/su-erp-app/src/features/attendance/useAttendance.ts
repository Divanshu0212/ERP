import type { AttendanceMark, CourseSummary } from '@api-types/index';
import { useMutation, useQuery } from '@tanstack/react-query';

import { request } from '@/lib/api/client';
import { getCurrentPosition } from '@/lib/device/geofence';
import { useConnectivity } from '@/lib/net/connectivity';
import { enqueue } from '@/lib/offline/queue';

export const SUMMARY_KEY = ['attendance', 'summary'];

export type Queued = { queued: true };

export function fetchSummary(): Promise<CourseSummary[]> {
  return request<CourseSummary[]>('/api/v1/attendance/summary');
}

export function useAttendanceSummary() {
  return useQuery({ queryKey: SUMMARY_KEY, queryFn: fetchSummary });
}

/**
 * Queueable, with one caveat worth knowing: a queued mark carries the code
 * that was current when it was captured, and the server accepts only the
 * current or previous bucket. So a mark queued for more than ~30 seconds
 * will be refused on replay and dropped. That is deliberate — accepting an
 * old code would reopen exactly the proxy hole the code exists to close.
 * The queue still helps the common case: a brief signal drop at submit time.
 */
export async function markAttendance(
  sessionId: string,
  code: string,
): Promise<AttendanceMark | Queued> {
  const position = await getCurrentPosition();
  const body = {
    lat: position.lat,
    lng: position.lng,
    code,
    mock_location: position.mocked,
  };
  const path = `/api/v1/attendance/sessions/${sessionId}/mark`;

  if (!useConnectivity.getState().online) {
    await enqueue(path, 'POST', body);
    return { queued: true };
  }

  return request<AttendanceMark>(path, { method: 'POST', body: JSON.stringify(body) });
}

export function useMarkAttendance() {
  return useMutation({
    mutationFn: ({ sessionId, code }: { sessionId: string; code: string }) =>
      markAttendance(sessionId, code),
  });
}
