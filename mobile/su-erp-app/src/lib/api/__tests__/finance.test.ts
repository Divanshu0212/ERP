import { useConnectivity } from '../../net/connectivity';
import {
  OfflineError,
  createInvoiceOrder,
  fetchInvoices,
  forgetInvoiceKey,
  payInvoice,
} from '../finance';

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

test('createInvoiceOrder opens a razorpay order for the invoice', async () => {
  request.mockResolvedValue({ order_id: 'order_1', amount: '4500.00', currency: 'INR', key_id: 'k' });

  await createInvoiceOrder('inv-1');

  expect(request).toHaveBeenCalledWith('/api/v1/finance/invoices/inv-1/razorpay-order', {
    method: 'POST',
  });
});

test('payInvoice posts an idempotency key with the invoice id', async () => {
  request.mockResolvedValue({});

  await payInvoice('inv-1');

  const body = JSON.parse(request.mock.calls[0][1].body);
  expect(body.invoice_id).toBe('inv-1');
  expect(body.idempotency_key).toMatch(/^[0-9a-f-]{36}$/);
});

test('payInvoice forwards the razorpay proof for server-side verification', async () => {
  request.mockResolvedValue({});

  await payInvoice('inv-proof', {
    razorpay_order_id: 'order_x',
    razorpay_payment_id: 'pay_x',
    razorpay_signature: 'sig_x',
  });

  const body = JSON.parse(request.mock.calls[0][1].body);
  expect(body.razorpay_order_id).toBe('order_x');
  expect(body.razorpay_signature).toBe('sig_x');
});

test('payInvoice refuses to run offline instead of queueing', async () => {
  useConnectivity.setState({ online: false });

  await expect(payInvoice('inv-1')).rejects.toBeInstanceOf(OfflineError);
  expect(request).not.toHaveBeenCalled();
});

test('createInvoiceOrder refuses to run offline', async () => {
  useConnectivity.setState({ online: false });

  await expect(createInvoiceOrder('inv-1')).rejects.toBeInstanceOf(OfflineError);
});

test('retrying the same payment reuses its idempotency key', async () => {
  request.mockResolvedValue({});

  await payInvoice('inv-retry');
  await payInvoice('inv-retry');

  const first = JSON.parse(request.mock.calls[0][1].body).idempotency_key;
  const second = JSON.parse(request.mock.calls[1][1].body).idempotency_key;
  expect(second).toBe(first);
});

test('a different invoice gets its own key', async () => {
  request.mockResolvedValue({});

  await payInvoice('inv-a');
  await payInvoice('inv-b');

  const first = JSON.parse(request.mock.calls[0][1].body).idempotency_key;
  const second = JSON.parse(request.mock.calls[1][1].body).idempotency_key;
  expect(second).not.toBe(first);
});

test('a settled invoice gets a fresh key for a genuinely new payment', async () => {
  request.mockResolvedValue({});

  await payInvoice('inv-settled');
  const first = JSON.parse(request.mock.calls[0][1].body).idempotency_key;

  forgetInvoiceKey('inv-settled');
  await payInvoice('inv-settled');
  const second = JSON.parse(request.mock.calls[1][1].body).idempotency_key;

  expect(second).not.toBe(first);
});
