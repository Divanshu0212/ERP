import { createRoomRequest, fetchAvailableRooms, fetchMyAllocations, fetchMyRoomRequests } from '../hostel';

jest.mock('../client', () => ({ request: jest.fn() }));
const { request } = jest.requireMock('../client');

beforeEach(() => request.mockReset());

test('fetchMyAllocations uses the student-scoped route, not the tenant list', async () => {
  request.mockResolvedValue({ results: [], count: 0, page: 1, num_pages: 1 });

  await fetchMyAllocations();

  expect(request).toHaveBeenCalledWith('/api/v1/hostel/allocations/mine');
});

test('fetchMyRoomRequests hits the mine endpoint', async () => {
  request.mockResolvedValue({ results: [], count: 0, page: 1, num_pages: 1 });

  await fetchMyRoomRequests();

  expect(request).toHaveBeenCalledWith('/api/v1/hostel/room-requests/mine');
});

test('createRoomRequest posts the chosen room', async () => {
  request.mockResolvedValue({ id: 'r1' });

  await createRoomRequest({ room_id: 'room-9' });

  expect(request).toHaveBeenCalledWith('/api/v1/hostel/room-requests', {
    method: 'POST',
    body: JSON.stringify({ room_id: 'room-9' }),
  });
});

test('fetchAvailableRooms hits the available rooms endpoint', async () => {
  request.mockResolvedValue({ results: [], count: 0, page: 1, num_pages: 1 });

  await fetchAvailableRooms();

  expect(request).toHaveBeenCalledWith('/api/v1/hostel/rooms/available');
});
