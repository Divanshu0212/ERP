import type { RazorpayOrder } from '@api-types/index';
import { useState } from 'react';

import { ApiError } from '@/lib/api/client';

import type { CheckoutResult } from './RazorpayCheckout';

interface PendingCheckout {
  order: RazorpayOrder;
  description: string;
  settle: (result: CheckoutResult) => void;
}

/**
 * Drives the three-step payment flow — open an order, run the widget, hand the
 * proof back — as one awaitable call, so screens do not have to model the
 * widget as extra state of their own.
 */
export function useCheckout() {
  const [pending, setPending] = useState<PendingCheckout | null>(null);

  /** Resolves when the student finishes or dismisses the widget. */
  function run(order: RazorpayOrder, description: string): Promise<CheckoutResult> {
    return new Promise((resolve) => {
      setPending({
        order,
        description,
        settle: (result) => {
          setPending(null);
          resolve(result);
        },
      });
    });
  }

  return { pending, run };
}

/**
 * A 400 from the razorpay-order endpoint means the server has no credentials,
 * not that anything is wrong. The caller should fall through to the simulated
 * gateway rather than showing the student an error.
 */
export function isUnconfiguredGateway(error: unknown): boolean {
  return error instanceof ApiError && error.status === 400;
}
