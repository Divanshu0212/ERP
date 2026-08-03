import { useConnectivity } from '@/lib/net/connectivity';

import { markAttendance } from '../useAttendance';

jest.mock('@/lib/api/client', () => ({ request: jest.fn() }));
jest.mock('@/lib/offline/queue', () => ({ enqueue: jest.fn(async () => ({ id: 'q1' })) }));
jest.mock('@/lib/device/geofence', () => ({
  getCurrentPosition: jest.fn(async () => ({ lat: 12.971599, lng: 77.594566, mocked: false })),
}));
jest.mock('@react-native-community/netinfo', () => ({ addEventListener: jest.fn(() => () => {}) }));

const { request } = jest.requireMock('@/lib/api/client');
const { enqueue } = jest.requireMock('@/lib/offline/queue');
const { getCurrentPosition } = jest.requireMock('@/lib/device/geofence');

beforeEach(() => {
  request.mockReset();
  enqueue.mockClear();
  getCurrentPosition.mockResolvedValue({ lat: 12.971599, lng: 77.594566, mocked: false });
  useConnectivity.setState({ online: true });
});

test('marking sends the position and the code', async () => {
  request.mockResolvedValue({ id: 'm1' });

  await markAttendance('s1', '123456');

  const body = JSON.parse(request.mock.calls[0][1].body);
  expect(body).toEqual({
    lat: 12.971599,
    lng: 77.594566,
    code: '123456',
    mock_location: false,
  });
});

test('a mocked location is reported honestly rather than hidden', async () => {
  getCurrentPosition.mockResolvedValue({ lat: 12.9, lng: 77.5, mocked: true });
  request.mockResolvedValue({ id: 'm1' });

  await markAttendance('s1', '123456').catch(() => undefined);

  const body = JSON.parse(request.mock.calls[0][1].body);
  expect(body.mock_location).toBe(true);
});

test('marking queues in a dead-zone classroom', async () => {
  useConnectivity.setState({ online: false });

  const result = await markAttendance('s1', '123456');

  expect(enqueue).toHaveBeenCalledWith(
    '/api/v1/attendance/sessions/s1/mark',
    'POST',
    expect.objectContaining({ code: '123456' }),
  );
  expect(result).toEqual({ queued: true });
});
