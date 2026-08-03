import { useConnectivity } from '../../net/connectivity';
import { NEXT_STATUS, advanceOrder, setItemAvailability } from '../owner';

jest.mock('../client', () => ({ request: jest.fn() }));
jest.mock('../../offline/queue', () => ({ enqueue: jest.fn(async () => ({ id: 'q1' })) }));
jest.mock('@react-native-community/netinfo', () => ({ addEventListener: jest.fn(() => () => {}) }));

const { request } = jest.requireMock('../client');
const { enqueue } = jest.requireMock('../../offline/queue');

beforeEach(() => {
  request.mockReset();
  enqueue.mockClear();
  useConnectivity.setState({ online: true });
});

test('the client transition table matches the kitchen flow', () => {
  expect(NEXT_STATUS.placed).toBe('preparing');
  expect(NEXT_STATUS.preparing).toBe('ready');
  expect(NEXT_STATUS.ready).toBe('completed');
  expect(NEXT_STATUS.completed).toBeNull();
  expect(NEXT_STATUS.cancelled).toBeNull();
});

test('advanceOrder patches the status endpoint when online', async () => {
  request.mockResolvedValue({ id: 'o1', status: 'preparing' });

  await advanceOrder('o1', 'preparing');

  expect(request).toHaveBeenCalledWith(
    '/api/v1/orders/o1/status/',
    expect.objectContaining({ method: 'PATCH' }),
  );
});

test('advanceOrder queues in the basement kitchen', async () => {
  useConnectivity.setState({ online: false });

  const result = await advanceOrder('o1', 'ready');

  expect(enqueue).toHaveBeenCalledWith('/api/v1/orders/o1/status/', 'PATCH', { status: 'ready' });
  expect(result).toEqual({ queued: true });
});

test('setItemAvailability patches the menu item', async () => {
  request.mockResolvedValue({ id: 'm1', available: false });

  await setItemAvailability('m1', false);

  const body = JSON.parse(request.mock.calls[0][1].body);
  expect(body).toEqual({ available: false });
});
