import { useQuery } from '@tanstack/react-query';

import { fetchMenu } from '@/lib/api/canteen';

export const MENU_KEY = ['canteen', 'menu'];

export function useMenu() {
  return useQuery({ queryKey: MENU_KEY, queryFn: fetchMenu });
}
