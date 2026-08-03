import type { Decimal, OrderStatus } from '@api-types/index';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { fetchMenu } from '@/lib/api/canteen';
import { advanceOrder, fetchOrderBoard, setItemAvailability, setItemPrice } from '@/lib/api/owner';

export const BOARD_KEY = ['owner', 'orders'];
export const OWNER_MENU_KEY = ['owner', 'menu'];

export function useOrderBoard() {
  return useQuery({
    queryKey: BOARD_KEY,
    queryFn: fetchOrderBoard,
    // The board is a live work surface — students place orders while it is
    // open, so it polls rather than waiting for a pull-to-refresh.
    refetchInterval: 10_000,
  });
}

export function useAdvanceOrder() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, status }: { id: string; status: OrderStatus }) => advanceOrder(id, status),
    onSuccess: () => client.invalidateQueries({ queryKey: BOARD_KEY }),
  });
}

export function useOwnerMenu() {
  return useQuery({ queryKey: OWNER_MENU_KEY, queryFn: fetchMenu });
}

export function useSetAvailability() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, available }: { id: string; available: boolean }) =>
      setItemAvailability(id, available),
    onSuccess: () => client.invalidateQueries({ queryKey: OWNER_MENU_KEY }),
  });
}

export function useSetPrice() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, price }: { id: string; price: Decimal }) => setItemPrice(id, price),
    onSuccess: () => client.invalidateQueries({ queryKey: OWNER_MENU_KEY }),
  });
}
