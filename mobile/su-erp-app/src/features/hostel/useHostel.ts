import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  createRoomRequest,
  fetchAvailableRooms,
  fetchMyAllocations,
  fetchMyRoomRequests,
} from '@/lib/api/hostel';

export const ALLOCATIONS_KEY = ['hostel', 'allocations', 'mine'];
export const ROOM_REQUESTS_KEY = ['hostel', 'room-requests'];
export const AVAILABLE_ROOMS_KEY = ['hostel', 'rooms', 'available'];

export function useMyAllocation() {
  const query = useQuery({ queryKey: ALLOCATIONS_KEY, queryFn: fetchMyAllocations });
  const mine = query.data?.results ?? [];

  return { ...query, mine, current: mine.find((a) => a.status === 'confirmed') };
}

export function useMyRoomRequests() {
  return useQuery({ queryKey: ROOM_REQUESTS_KEY, queryFn: fetchMyRoomRequests });
}

export function useAvailableRooms(enabled: boolean) {
  return useQuery({
    queryKey: AVAILABLE_ROOMS_KEY,
    queryFn: fetchAvailableRooms,
    enabled,
  });
}

export function useRequestRoom() {
  const client = useQueryClient();

  return useMutation({
    mutationFn: createRoomRequest,
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ROOM_REQUESTS_KEY });
      // A claimed seat changes what is still available to everyone else.
      void client.invalidateQueries({ queryKey: AVAILABLE_ROOMS_KEY });
    },
  });
}
