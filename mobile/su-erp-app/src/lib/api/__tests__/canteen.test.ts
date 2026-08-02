import { useConnectivity } from '../../net/connectivity';
import { fetchMenu, fetchOrders, placeOrder } from '../canteen';
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

test('placeOrder posts the cart lines', async () => {
  request.mockResolvedValue({ id: 'o1' });

  await placeOrder([{ menu_item_id: 'm1', quantity: 2 }]);

  const body = JSON.parse(request.mock.calls[0][1].body);
  expect(body.items).toEqual([{ menu_item_id: 'm1', quantity: 2 }]);
});

test('placeOrder refuses to run offline', async () => {
  useConnectivity.setState({ online: false });

  await expect(placeOrder([{ menu_item_id: 'm1', quantity: 1 }])).rejects.toBeInstanceOf(
    OfflineError,
  );
  expect(request).not.toHaveBeenCalled();
});
