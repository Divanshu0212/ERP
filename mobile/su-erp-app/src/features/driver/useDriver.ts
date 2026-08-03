import type { BreadcrumbPoint, Trip } from '@api-types/index';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useCallback, useEffect, useRef, useState } from 'react';

import { endTrip, fetchManifest, fetchMySchedules, sendBreadcrumbs, startTrip } from '@/lib/api/driver';
import { requestPermission, watchPosition } from '@/lib/device/location';

export const SCHEDULES_KEY = ['driver', 'schedules'];
export const MANIFEST_KEY = ['driver', 'manifest'];

/** How often buffered points are flushed to the server (or the queue). */
const FLUSH_INTERVAL_MS = 30_000;

export function useMySchedules() {
  return useQuery({ queryKey: SCHEDULES_KEY, queryFn: fetchMySchedules });
}

export function useManifest(scheduleId: string | undefined) {
  return useQuery({
    queryKey: [...MANIFEST_KEY, scheduleId],
    queryFn: () => fetchManifest(scheduleId as string),
    enabled: Boolean(scheduleId),
  });
}

/**
 * Owns the active trip and the GPS stream that belongs to it. Points are
 * buffered and flushed in batches rather than sent one at a time — one
 * request every 15 seconds would drain a driver's battery over a full route.
 */
export function useActiveTrip() {
  const [trip, setTrip] = useState<Trip | null>(null);
  const buffer = useRef<BreadcrumbPoint[]>([]);
  const stopWatch = useRef<(() => void) | null>(null);

  const flush = useCallback(async (tripId: string) => {
    if (buffer.current.length === 0) return;
    const points = buffer.current;
    buffer.current = [];
    await sendBreadcrumbs(tripId, points);
  }, []);

  const start = useMutation({
    mutationFn: async (scheduleId: string) => {
      const granted = await requestPermission();
      if (!granted) throw new Error('Location permission is required to run a trip.');

      const started = await startTrip(scheduleId);
      stopWatch.current = await watchPosition((point) => buffer.current.push(point));
      setTrip(started);
      return started;
    },
  });

  const end = useMutation({
    mutationFn: async () => {
      if (!trip) throw new Error('No active trip.');
      stopWatch.current?.();
      stopWatch.current = null;
      // Flush before ending so the tail of the route is not dropped.
      await flush(trip.id);
      const ended = await endTrip(trip.id);
      setTrip(null);
      return ended;
    },
  });

  useEffect(() => {
    if (!trip) return undefined;
    const timer = setInterval(() => void flush(trip.id), FLUSH_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [trip, flush]);

  // Unmounting mid-trip must not leave the GPS subscription running.
  useEffect(() => () => stopWatch.current?.(), []);

  return { trip, start, end };
}
