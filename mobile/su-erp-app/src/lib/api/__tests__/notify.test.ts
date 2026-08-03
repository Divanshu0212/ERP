import { fetchInbox, markRead } from '../notify';

jest.mock('../client', () => ({ request: jest.fn() }));
const { request } = jest.requireMock('../client');

beforeEach(() => request.mockReset());

test('fetchInbox hits the inbox endpoint', async () => {
  request.mockResolvedValue({ results: [], count: 0, page: 1, num_pages: 1 });

  await fetchInbox();

  expect(request).toHaveBeenCalledWith('/api/v1/notify/inbox');
});

test('fetchInbox passes the page number', async () => {
  request.mockResolvedValue({ results: [], count: 0, page: 2, num_pages: 2 });

  await fetchInbox(2);

  expect(request).toHaveBeenCalledWith('/api/v1/notify/inbox?page=2');
});

test('markRead posts to the read endpoint', async () => {
  request.mockResolvedValue(undefined);

  await markRead('abc');

  expect(request).toHaveBeenCalledWith('/api/v1/notify/inbox/abc/read', { method: 'POST' });
});
