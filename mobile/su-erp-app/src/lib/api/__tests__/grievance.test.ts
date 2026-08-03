import { useConnectivity } from '../../net/connectivity';
import { createTicket, fetchTickets } from '../grievance';

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

test('fetchTickets hits the grievance endpoint', async () => {
  request.mockResolvedValue({ results: [], count: 0, page: 1, num_pages: 1 });

  await fetchTickets();

  expect(request).toHaveBeenCalledWith('/api/v1/grievance');
});

test('createTicket posts directly when online', async () => {
  request.mockResolvedValue({ id: 't1' });

  await createTicket({ category: 'hostel', description: 'Fan broken in room 12' });

  expect(request).toHaveBeenCalled();
  expect(enqueue).not.toHaveBeenCalled();
});

test('createTicket queues when offline instead of failing', async () => {
  useConnectivity.setState({ online: false });

  const result = await createTicket({
    category: 'hostel',
    description: 'Fan broken in room 12',
  });

  expect(enqueue).toHaveBeenCalledWith(
    '/api/v1/grievance',
    'POST',
    expect.objectContaining({ category: 'hostel' }),
  );
  expect(result).toEqual({ queued: true });
  expect(request).not.toHaveBeenCalled();
});

test('a queued ticket is reported as queued, not as a saved ticket', async () => {
  useConnectivity.setState({ online: false });

  const result = await createTicket({ category: 'it', description: 'Wifi down' });

  expect('queued' in result).toBe(true);
});
