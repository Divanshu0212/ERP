import type { CartLine } from '@api-types/index';
import { create } from 'zustand';

interface CartState {
  lines: Record<string, number>;
  add(menuItemId: string): void;
  remove(menuItemId: string): void;
  clear(): void;
  toLines(): CartLine[];
  count(): number;
}

export const useCart = create<CartState>((set, get) => ({
  lines: {},

  add: (id) => set((s) => ({ lines: { ...s.lines, [id]: (s.lines[id] ?? 0) + 1 } })),

  remove: (id) =>
    set((s) => {
      const next = (s.lines[id] ?? 0) - 1;
      const lines = { ...s.lines };
      if (next <= 0) delete lines[id];
      else lines[id] = next;
      return { lines };
    }),

  clear: () => set({ lines: {} }),

  toLines: () =>
    Object.entries(get().lines).map(([menu_item_id, quantity]) => ({ menu_item_id, quantity })),

  count: () => Object.values(get().lines).reduce((sum, n) => sum + n, 0),
}));
