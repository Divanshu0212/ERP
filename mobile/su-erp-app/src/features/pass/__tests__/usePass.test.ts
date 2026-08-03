import { useConnectivity } from '@/lib/net/connectivity';

import { submitScan } from '../usePass';

jest.mock('@/lib/api/client', () => ({ request: jest.fn() }));
jest.mock('@/lib/offline/queue', () => ({ enqueue: jest.fn(async () => ({ id: 'q1' })) }));
jest.mock('@react-native-community/netinfo', () => ({ addEventListener: jest.fn(() => () => {}) }));

const { request } = jest.requireMock('@/lib/api/client');
const { enqueue } = jest.requireMock('@/lib/offline/queue');

beforeEach(() => {
  request.mockReset();
  enqueue.mockClear();
  useConnectivity.setState({ online: true });
});

test('a scan posts immediately when online', async () => {
  request.mockResolvedValue({ accepted: true, student_user_code: 'STU-001' });

  const result = await submitScan('tok');

  expect(request).toHaveBeenCalledWith(
    '/api/v1/transport/scans',
    expect.objectContaining({ method: 'POST' }),
  );
  expect(result).toEqual({ accepted: true, student_user_code: 'STU-001' });
});

test('a scan on a moving bus queues when offline', async () => {
  useConnectivity.setState({ online: false });

  const result = await submitScan('tok');

  expect(enqueue).toHaveBeenCalledWith('/api/v1/transport/scans', 'POST', { token: 'tok' });
  expect(result).toEqual({ queued: true });
  expect(request).not.toHaveBeenCalled();
});
