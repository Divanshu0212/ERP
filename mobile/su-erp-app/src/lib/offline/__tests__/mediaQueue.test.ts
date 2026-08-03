import { createMemoryMediaStore, enqueueMedia, replayMedia, setMediaStore } from '../mediaQueue';

jest.mock('@/lib/api/client', () => ({ request: jest.fn() }));
jest.mock('expo-file-system/legacy', () => ({ deleteAsync: jest.fn(async () => {}) }));

const { request } = jest.requireMock('@/lib/api/client');
const { deleteAsync } = jest.requireMock('expo-file-system/legacy');

beforeEach(() => {
  setMediaStore(createMemoryMediaStore());
  request.mockReset();
  deleteAsync.mockClear();
});

test('a successful upload removes the local file', async () => {
  request.mockResolvedValue({ id: 'm1' });
  await enqueueMedia('t1', 'file:///tmp/fan.jpg');

  const result = await replayMedia();

  expect(result.sent).toBe(1);
  expect(deleteAsync).toHaveBeenCalledWith('file:///tmp/fan.jpg', { idempotent: true });
});

test('a failed upload keeps the file for the next attempt', async () => {
  request.mockRejectedValue(new Error('network down'));
  await enqueueMedia('t1', 'file:///tmp/fan.jpg');

  const result = await replayMedia();

  expect(result.failed).toBe(1);
  expect(deleteAsync).not.toHaveBeenCalled();
});
