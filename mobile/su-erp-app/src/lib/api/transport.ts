import type { Booking, Paginated, Route, ScheduleSeats } from '@api-types/index';

import { useConnectivity } from '../net/connectivity';
import { request } from './client';
import { OfflineError } from './finance';
import { idempotencyKeyFor } from './idempotency';

export function fetchRoutes(): Promise<Paginated<Route>> {
  return request<Paginated<Route>>('/api/v1/transport/routes');
}

/**
 * Seat availability for every schedule on a route. Returns a bare array, not a
 * paginated envelope — RouteSeatsView builds the rows by hand.
 */
export function fetchSeats(routeId: string): Promise<ScheduleSeats[]> {
  return request<ScheduleSeats[]>(`/api/v1/transport/routes/${routeId}/seats`);
}

/**
 * Online-only. A seat is a scarce resource with a DB-level uniqueness
 * constraint behind it — a booking replayed twenty minutes later would be
 * claiming a seat that is very likely already gone, and the student would
 * believe they had one.
 */
export async function bookSeat(scheduleId: string, seatNo: number): Promise<Booking> {
  if (!useConnectivity.getState().online) throw new OfflineError();

  return request<Booking>('/api/v1/transport/bookings', {
    method: 'POST',
    body: JSON.stringify({
      schedule_id: scheduleId,
      seat_no: seatNo,
      idempotency_key: idempotencyKeyFor(`seat:${scheduleId}:${seatNo}`),
    }),
  });
}
