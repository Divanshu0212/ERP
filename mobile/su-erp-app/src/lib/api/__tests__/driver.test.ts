import { useConnectivity } from '../../net/connectivity';
import { endTrip, sendBreadcrumbs, startTrip } from '../driver';
import { OfflineError } from '../finance';

jest.mock('../client', () => ({ request: jest.fn() }));
jest.mock('../../offline/queue', () => ({ enqueue: jest.fn(async () => ({ id: 'q1' })) }));
jest.mock('@react-native-community/netinfo', () => ({ addEventListener: jest.fn(() => () => {}) }));

const { request } = jest.requireMock('../client');
const { enqueue } = jest.requireMock('../../offline/queue');

const POINT = { lat: '12.97', lng: '77.59', recorded_at: '2026-08-04T08:01:00Z' };

beforeEach(() => {
  request.mockReset();
  enqueue.mockClear();
  useConnectivity.setState({ online: true });
});

test('startTrip posts to the schedule trips endpoint', async () => {
  request.mockResolvedValue({ id: 'trip-1' });

  await startTrip('sched-1');

  expect(request).toHaveBeenCalledWith(
    '/api/v1/transport/schedules/sched-1/trips',
    expect.objectContaining({ method: 'POST' }),
  );
});

test('startTrip refuses to run offline', async () => {
  useConnectivity.setState({ online: false });
  await expect(startTrip('sched-1')).rejects.toBeInstanceOf(OfflineError);
});

test('endTrip posts to the end endpoint', async () => {
  request.mockResolvedValue({ id: 'trip-1', ended_at: 'now' });

  await endTrip('trip-1');

  expect(request).toHaveBeenCalledWith(
    '/api/v1/transport/trips/trip-1/end',
    expect.objectContaining({ method: 'POST' }),
  );
});

test('sendBreadcrumbs posts the batch when online', async () => {
  request.mockResolvedValue({ accepted: 1 });

  await sendBreadcrumbs('trip-1', [POINT]);

  const body = JSON.parse(request.mock.calls[0][1].body);
  expect(body.points).toEqual([POINT]);
  expect(enqueue).not.toHaveBeenCalled();
});

test('sendBreadcrumbs queues the batch through a tunnel', async () => {
  useConnectivity.setState({ online: false });

  await sendBreadcrumbs('trip-1', [POINT]);

  expect(enqueue).toHaveBeenCalledWith('/api/v1/transport/trips/trip-1/breadcrumbs', 'POST', {
    points: [POINT],
  });
  expect(request).not.toHaveBeenCalled();
});
