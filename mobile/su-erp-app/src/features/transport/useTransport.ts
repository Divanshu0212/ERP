import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { bookSeat, fetchRoutes, fetchSeats } from '@/lib/api/transport';

export const ROUTES_KEY = ['transport', 'routes'];
export const seatsKey = (routeId: string) => ['transport', 'seats', routeId];

export function useRoutes() {
  return useQuery({ queryKey: ROUTES_KEY, queryFn: fetchRoutes });
}

export function useSeats(routeId: string | null) {
  return useQuery({
    queryKey: seatsKey(routeId ?? ''),
    queryFn: () => fetchSeats(routeId as string),
    enabled: Boolean(routeId),
    // Seats go fast at peak hours; a stale map means tapping a seat someone
    // else already took.
    staleTime: 10_000,
  });
}

/**
 * A booking belongs to a BusSchedule (a specific bus at a specific time), not
 * to a Route — see transport/models.py Booking.schedule. The route selection
 * narrows which schedules to show; the schedule is what gets booked.
 */
export function useBookSeat(scheduleId: string | null, routeId: string | null) {
  const client = useQueryClient();

  return useMutation({
    mutationFn: (seatNo: number) => bookSeat(scheduleId as string, seatNo),
    onSuccess: () => client.invalidateQueries({ queryKey: seatsKey(routeId ?? '') }),
  });
}
