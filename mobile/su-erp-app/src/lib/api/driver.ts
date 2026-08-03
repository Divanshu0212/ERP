import type { Booking, BreadcrumbPoint, BusSchedule, Paginated, Trip } from '@api-types/index';

import { useConnectivity } from '../net/connectivity';
import { enqueue } from '../offline/queue';
import { request } from './client';
import { OfflineError } from './finance';

function offline(): boolean {
  return !useConnectivity.getState().online;
}

export function fetchMySchedules(): Promise<Paginated<BusSchedule>> {
  return request<Paginated<BusSchedule>>('/api/v1/transport/schedules/mine');
}

/**
 * Online-only: breadcrumbs are addressed to a trip id that only the server
 * can mint, so a queued start would leave every later point with nowhere to
 * go. The driver taps this at the depot, where signal exists.
 */
export async function startTrip(scheduleId: string): Promise<Trip> {
  if (offline()) throw new OfflineError('Connect to the network to start your trip.');
  return request<Trip>(`/api/v1/transport/schedules/${scheduleId}/trips`, { method: 'POST' });
}

export async function endTrip(tripId: string): Promise<Trip> {
  if (offline()) throw new OfflineError('Connect to the network to end your trip.');
  return request<Trip>(`/api/v1/transport/trips/${tripId}/end`, { method: 'POST' });
}

/**
 * Queueable, and the reason the queue exists. A bus spends minutes at a
 * time with no signal; points are buffered with their on-device timestamps
 * and replayed as a batch, so the trail keeps its real shape instead of
 * collapsing into the moment the signal returned.
 */
export async function sendBreadcrumbs(tripId: string, points: BreadcrumbPoint[]): Promise<void> {
  const path = `/api/v1/transport/trips/${tripId}/breadcrumbs`;

  if (offline()) {
    await enqueue(path, 'POST', { points });
    return;
  }

  await request<void>(path, { method: 'POST', body: JSON.stringify({ points }) });
}

export function fetchManifest(scheduleId: string): Promise<Paginated<Booking>> {
  return request<Paginated<Booking>>(`/api/v1/transport/schedules/${scheduleId}/bookings`);
}
