import { useConnectivity } from '../../net/connectivity';
import { OfflineError, fetchInvoices, payInvoice } from '../finance';

jest.mock('../client', () => ({ request: jest.fn() }));
jest.mock('@react-native-community/netinfo', () => ({ addEventListener: jest.fn(() => () => {}) }));
const { request } = jest.requireMock('../client');

beforeEach(() => {
  request.mockReset();
  useConnectivity.setState({ online: true });
});

test('fetchInvoices hits the invoices endpoint', async () => {
  request.mockResolvedValue({ results: [], count: 0, page: 1, num_pages: 1 });

  await fetchInvoices();

  expect(request).toHaveBeenCalledWith('/api/v1/finance/invoices');
});

test('payInvoice posts an idempotency key with the invoice id', async () => {
  request.mockResolvedValue({});

  await payInvoice('inv-1');

  const body = JSON.parse(request.mock.calls[0][1].body);
  expect(body.invoice_id).toBe('inv-1');
  expect(body.idempotency_key).toMatch(/^[0-9a-f-]{36}$/);
});

test('payInvoice refuses to run offline instead of queueing', async () => {
  useConnectivity.setState({ online: false });

  await expect(payInvoice('inv-1')).rejects.toBeInstanceOf(OfflineError);
  expect(request).not.toHaveBeenCalled();
});

test('retrying the same payment reuses its idempotency key', async () => {
  request.mockResolvedValue({});

  await payInvoice('inv-1');
  await payInvoice('inv-1');

  const first = JSON.parse(request.mock.calls[0][1].body).idempotency_key;
  const second = JSON.parse(request.mock.calls[1][1].body).idempotency_key;
  expect(second).toBe(first);
});

test('a different invoice gets its own key', async () => {
  request.mockResolvedValue({});

  await payInvoice('inv-1');
  await payInvoice('inv-2');

  const first = JSON.parse(request.mock.calls[0][1].body).idempotency_key;
  const second = JSON.parse(request.mock.calls[1][1].body).idempotency_key;
  expect(second).not.toBe(first);
});
