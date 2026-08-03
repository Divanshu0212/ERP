import { useConnectivity } from '../../net/connectivity';
import { checkoutCart, fetchMenu, fetchOrders, placeOrder } from '../canteen';
import { OfflineError } from '../finance';

jest.mock('../client', () => ({ request: jest.fn() }));
jest.mock('@react-native-community/netinfo', () => ({ addEventListener: jest.fn(() => () => {}) }));
const { request } = jest.requireMock('../client');

beforeEach(() => {
  request.mockReset();
  useConnectivity.setState({ online: true });
});

test('fetchMenu hits the menu endpoint', async () => {
  request.mockResolvedValue({ results: [], count: 0, page: 1, num_pages: 1 });

  await fetchMenu();

  expect(request).toHaveBeenCalledWith('/api/v1/menu-items/');
});

test('fetchOrders hits the orders endpoint', async () => {
  request.mockResolvedValue({ results: [], count: 0, page: 1, num_pages: 1 });

  await fetchOrders();

  expect(request).toHaveBeenCalledWith('/api/v1/orders/');
});

test('checkoutCart prices the cart without creating an order', async () => {
  request.mockResolvedValue({ order_id: 'SIM-1', amount: '120.00', currency: 'INR', key_id: '' });

  await checkoutCart([{ menu_item_id: 'm1', quantity: 2 }]);

  expect(request).toHaveBeenCalledWith('/api/v1/orders/checkout', expect.anything());
  const body = JSON.parse(request.mock.calls[0][1].body);
  expect(body.items).toEqual([{ menu_item_id: 'm1', quantity: 2 }]);
});

test('placeOrder posts the cart lines', async () => {
  request.mockResolvedValue({ id: 'o1' });

  await placeOrder([{ menu_item_id: 'm1', quantity: 2 }]);

  const body = JSON.parse(request.mock.calls[0][1].body);
  expect(body.items).toEqual([{ menu_item_id: 'm1', quantity: 2 }]);
});

test('placeOrder forwards the razorpay proof for server-side verification', async () => {
  request.mockResolvedValue({ id: 'o1' });

  await placeOrder([{ menu_item_id: 'm1', quantity: 1 }], {
    razorpay_order_id: 'order_x',
    razorpay_payment_id: 'pay_x',
    razorpay_signature: 'sig_x',
  });

  const body = JSON.parse(request.mock.calls[0][1].body);
  expect(body.razorpay_order_id).toBe('order_x');
  expect(body.razorpay_payment_id).toBe('pay_x');
  expect(body.razorpay_signature).toBe('sig_x');
});

test('placeOrder refuses to run offline', async () => {
  useConnectivity.setState({ online: false });

  await expect(placeOrder([{ menu_item_id: 'm1', quantity: 1 }])).rejects.toBeInstanceOf(
    OfflineError,
  );
  expect(request).not.toHaveBeenCalled();
});

test('checkoutCart refuses to run offline', async () => {
  useConnectivity.setState({ online: false });

  await expect(checkoutCart([{ menu_item_id: 'm1', quantity: 1 }])).rejects.toBeInstanceOf(
    OfflineError,
  );
});
