import type { LivePosition } from '@api-types/index';
import { useQuery } from '@tanstack/react-query';

import { request } from '@/lib/api/client';

export const liveBusKey = (routeId: string) => ['transport', 'live', routeId];

export function useLiveBus(routeId: string | null) {
  return useQuery({
    queryKey: liveBusKey(routeId ?? ''),
    queryFn: () => request<LivePosition>(`/api/v1/transport/routes/${routeId}/live`),
    enabled: Boolean(routeId),
    // The server's own key expires after 60s, so polling faster than the
    // driver's 15s broadcast interval would only return the same point.
    refetchInterval: 15_000,
    // A 404 means no bus is running — not an error worth retrying.
    retry: false,
  });
}
