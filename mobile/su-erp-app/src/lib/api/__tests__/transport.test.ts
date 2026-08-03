import { useConnectivity } from '../../net/connectivity';
import { OfflineError } from '../finance';
import { bookSeat, fetchRoutes, fetchSeats } from '../transport';

jest.mock('../client', () => ({ request: jest.fn() }));
jest.mock('@react-native-community/netinfo', () => ({ addEventListener: jest.fn(() => () => {}) }));
const { request } = jest.requireMock('../client');

beforeEach(() => {
  request.mockReset();
  useConnectivity.setState({ online: true });
});

test('fetchRoutes hits the routes endpoint', async () => {
  request.mockResolvedValue({ results: [], count: 0, page: 1, num_pages: 1 });

  await fetchRoutes();

  expect(request).toHaveBeenCalledWith('/api/v1/transport/routes');
});

test('fetchSeats hits the per-route seats endpoint', async () => {
  request.mockResolvedValue([]);

  await fetchSeats('r1');

  expect(request).toHaveBeenCalledWith('/api/v1/transport/routes/r1/seats');
});

test('bookSeat posts the schedule id and seat number', async () => {
  request.mockResolvedValue({ id: 'b1' });

  await bookSeat('sched-1', 4);

  const body = JSON.parse(request.mock.calls[0][1].body);
  expect(body.schedule_id).toBe('sched-1');
  expect(body.seat_no).toBe(4);
});

test('bookSeat sends an idempotency key so a retry cannot double-book', async () => {
  request.mockResolvedValue({ id: 'b1' });

  await bookSeat('sched-1', 4);

  const body = JSON.parse(request.mock.calls[0][1].body);
  expect(body.idempotency_key).toMatch(/^[0-9a-f-]{36}$/);
});

test('retrying the same seat reuses its idempotency key', async () => {
  request.mockResolvedValue({ id: 'b1' });

  await bookSeat('sched-1', 4);
  await bookSeat('sched-1', 4);

  const first = JSON.parse(request.mock.calls[0][1].body).idempotency_key;
  const second = JSON.parse(request.mock.calls[1][1].body).idempotency_key;
  expect(second).toBe(first);
});

test('a different seat gets its own key', async () => {
  request.mockResolvedValue({ id: 'b1' });

  await bookSeat('sched-1', 4);
  await bookSeat('sched-1', 5);

  const first = JSON.parse(request.mock.calls[0][1].body).idempotency_key;
  const second = JSON.parse(request.mock.calls[1][1].body).idempotency_key;
  expect(second).not.toBe(first);
});

test('bookSeat refuses to run offline', async () => {
  useConnectivity.setState({ online: false });

  await expect(bookSeat('sched-1', 4)).rejects.toBeInstanceOf(OfflineError);
  expect(request).not.toHaveBeenCalled();
});
