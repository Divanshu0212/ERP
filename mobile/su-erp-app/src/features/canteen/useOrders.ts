import type { Order, Paginated } from '@api-types/index';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { checkoutCart, fetchOrders, placeOrder } from '@/lib/api/canteen';

import type { CheckoutResult } from '../payments/RazorpayCheckout';
import { useCart } from './useCart';

export const ORDERS_KEY = ['canteen', 'orders'];

/** An order still moving through the kitchen. */
export function isActive(order: Order): boolean {
  return order.status !== 'completed' && order.status !== 'cancelled';
}

/** The stages an order passes through, in order, for the progress indicator. */
export const ORDER_STAGES: Order['status'][] = ['placed', 'preparing', 'ready'];

export const ORDER_STATUS_COPY: Record<Order['status'], string> = {
  placed: 'Order placed',
  preparing: 'Being prepared',
  ready: 'Ready for pickup',
  completed: 'Collected',
  cancelled: 'Cancelled',
};

export function useOrders() {
  return useQuery({
    queryKey: ORDERS_KEY,
    queryFn: fetchOrders,

    /**
     * An in-flight order changes state in the kitchen, not on this device, so
     * "ready" has to arrive without a manual pull. Polling stops once nothing
     * is active — a student reading the menu should not be paying for a
     * request every 15 seconds in battery and campus bandwidth.
     */
    refetchInterval: (query) => {
      const data = query.state.data as Paginated<Order> | undefined;
      return (data?.results ?? []).some(isActive) ? 15_000 : false;
    },
  });
}

export function usePlaceOrder(
  runCheckout: (order: Awaited<ReturnType<typeof checkoutCart>>, description: string) => Promise<CheckoutResult>,
) {
  const client = useQueryClient();
  const clearCart = useCart((s) => s.clear);

  return useMutation({
    mutationFn: async () => {
      const lines = useCart.getState().toLines();

      // The cart is priced server-side — the device never decides what the
      // food costs, so a tampered total cannot underpay.
      const order = await checkoutCart(lines);

      const result = await runCheckout(order, 'Canteen order');
      if (result.type === 'cancelled') throw new OrderCancelled();
      if (result.type === 'failed') throw new Error(result.message ?? 'Payment failed.');

      return placeOrder(lines, result.proof);
    },

    onSuccess: () => {
      clearCart();
      void client.invalidateQueries({ queryKey: ORDERS_KEY });
    },
  });
}

/** Backing out of the payment sheet is a choice, not an error to report. */
export class OrderCancelled extends Error {
  constructor() {
    super('Order cancelled.');
    this.name = 'OrderCancelled';
  }
}
