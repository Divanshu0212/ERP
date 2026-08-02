import type { Order, Paginated } from '@api-types/index';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { fetchOrders, placeOrder } from '@/lib/api/canteen';

import { useCart } from './useCart';

export const ORDERS_KEY = ['canteen', 'orders'];

/** An order still moving through the kitchen. */
export function isActive(order: Order): boolean {
  return order.status !== 'completed' && order.status !== 'cancelled';
}

export function useOrders() {
  return useQuery({
    queryKey: ORDERS_KEY,
    queryFn: fetchOrders,

    /**
     * An in-flight order changes state in the kitchen, not on this device, so
     * "ready" has to arrive without a manual pull. Polling stops once nothing
     * is active — a student browsing the menu should not be paying for a
     * request every 15 seconds in battery and campus bandwidth.
     */
    refetchInterval: (query) => {
      const data = query.state.data as Paginated<Order> | undefined;
      const active = (data?.results ?? []).some(isActive);
      return active ? 15_000 : false;
    },
  });
}

export function usePlaceOrder() {
  const client = useQueryClient();
  const clearCart = useCart((s) => s.clear);

  return useMutation({
    mutationFn: placeOrder,
    onSuccess: () => {
      clearCart();
      void client.invalidateQueries({ queryKey: ORDERS_KEY });
    },
  });
}
