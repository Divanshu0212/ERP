import type { Decimal } from './finance';

export type OrderStatus = 'placed' | 'preparing' | 'ready' | 'completed' | 'cancelled';

/** canteen/serializers.py MenuItemSerializer. */
export interface MenuItem {
  id: string;
  name: string;
  price: Decimal;
  available: boolean;
  created_at: string;
}

/** canteen/serializers.py OrderItemSerializer. */
export interface OrderItem {
  id: string;
  menu_item_id: string;
  name: string;
  quantity: number;
  unit_price: Decimal;
}

/** canteen/serializers.py OrderSerializer. */
export interface Order {
  id: string;
  student_user_code: string;
  status: OrderStatus;
  total: Decimal;
  items: OrderItem[];
  created_at: string;
  updated_at: string;
}

/** One line of an outgoing order — OrderItemInputSerializer. */
export interface CartLine {
  menu_item_id: string;
  quantity: number;
}
