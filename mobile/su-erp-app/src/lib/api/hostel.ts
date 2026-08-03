import type { Allocation, Paginated, Room, RoomRequest, RoomRequestInput } from '@api-types/index';

import { request } from './client';

/**
 * The caller's own allocations. GET /allocations is tenant-scoped — it answers
 * "every allocation in this institution", which a student must never receive —
 * so the student surface uses this route instead of filtering on the client.
 */
export function fetchMyAllocations(): Promise<Paginated<Allocation>> {
  return request<Paginated<Allocation>>('/api/v1/hostel/allocations/mine');
}

export function fetchMyRoomRequests(): Promise<Paginated<RoomRequest>> {
  return request<Paginated<RoomRequest>>('/api/v1/hostel/room-requests/mine');
}

export function fetchAvailableRooms(): Promise<Paginated<Room>> {
  return request<Paginated<Room>>('/api/v1/hostel/rooms/available');
}

/** RoomRequestCreateSerializer takes a specific room, not free-form preferences. */
export function createRoomRequest(input: RoomRequestInput): Promise<RoomRequest> {
  return request<RoomRequest>('/api/v1/hostel/room-requests', {
    method: 'POST',
    body: JSON.stringify(input),
  });
}
