import { useCart } from '../useCart';

beforeEach(() => useCart.getState().clear());

test('adding an item sets quantity to one', () => {
  useCart.getState().add('m1');
  expect(useCart.getState().lines.m1).toBe(1);
});

test('adding the same item twice increments it', () => {
  useCart.getState().add('m1');
  useCart.getState().add('m1');
  expect(useCart.getState().lines.m1).toBe(2);
});

test('removing decrements and drops the line at zero', () => {
  useCart.getState().add('m1');
  useCart.getState().remove('m1');
  expect(useCart.getState().lines.m1).toBeUndefined();
});

test('removing an item that is not in the cart is a no-op', () => {
  useCart.getState().remove('ghost');
  expect(useCart.getState().lines.ghost).toBeUndefined();
});

test('toLines converts the map to the request shape', () => {
  useCart.getState().add('m1');
  useCart.getState().add('m2');
  useCart.getState().add('m2');

  expect(useCart.getState().toLines()).toEqual([
    { menu_item_id: 'm1', quantity: 1 },
    { menu_item_id: 'm2', quantity: 2 },
  ]);
});

test('count sums every quantity', () => {
  useCart.getState().add('m1');
  useCart.getState().add('m2');
  useCart.getState().add('m2');
  expect(useCart.getState().count()).toBe(3);
});
