import { useConnectivity } from '../../net/connectivity';
import {
  checkoutVisitor,
  fetchBlockRoster,
  fetchVisitors,
  logVisitor,
  setTicketStatus,
} from '../warden';

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

// /allocations/mine is role_required("student") and 403s for a warden, so the
// roster must go through the tenant-scoped list instead.
test('fetchBlockRoster reads the tenant allocation list, not /mine', async () => {
  request.mockResolvedValue({ results: [], count: 0, page: 1, num_pages: 1 });

  await fetchBlockRoster();

  expect(request).toHaveBeenCalledWith('/api/v1/hostel/allocations?status=confirmed');
});

test('fetchVisitors defaults to those still inside', async () => {
  request.mockResolvedValue({ results: [], count: 0, page: 1, num_pages: 1 });
  await fetchVisitors();
  expect(request).toHaveBeenCalledWith('/api/v1/hostel/visitors');
});

test('fetchVisitors can ask for the full history', async () => {
  request.mockResolvedValue({ results: [], count: 0, page: 1, num_pages: 1 });
  await fetchVisitors(true);
  expect(request).toHaveBeenCalledWith('/api/v1/hostel/visitors?all=true');
});

test('logVisitor posts directly when online', async () => {
  request.mockResolvedValue({ id: 'v1' });
  await logVisitor({ visitor_name: 'Asha', visiting_user_code: 'STU-001' });
  expect(request).toHaveBeenCalled();
  expect(enqueue).not.toHaveBeenCalled();
});

test('logVisitor queues at the gate when offline', async () => {
  useConnectivity.setState({ online: false });

  const result = await logVisitor({ visitor_name: 'Asha', visiting_user_code: 'STU-001' });

  expect(enqueue).toHaveBeenCalledWith(
    '/api/v1/hostel/visitors',
    'POST',
    expect.objectContaining({ visitor_name: 'Asha' }),
  );
  expect(result).toEqual({ queued: true });
});

test('checkoutVisitor queues when offline', async () => {
  useConnectivity.setState({ online: false });

  await checkoutVisitor('v1');

  expect(enqueue).toHaveBeenCalledWith('/api/v1/hostel/visitors/v1/checkout', 'POST', {});
});

test('setTicketStatus patches the status endpoint when online', async () => {
  request.mockResolvedValue({ id: 't1', status: 'resolved' });

  await setTicketStatus('t1', 'resolved');

  expect(request).toHaveBeenCalledWith(
    '/api/v1/grievance/t1/status',
    expect.objectContaining({ method: 'PATCH' }),
  );
});

test('setTicketStatus queues when offline', async () => {
  useConnectivity.setState({ online: false });

  const result = await setTicketStatus('t1', 'resolved');

  expect(enqueue).toHaveBeenCalledWith('/api/v1/grievance/t1/status', 'PATCH', {
    status: 'resolved',
  });
  expect(result).toEqual({ queued: true });
});
