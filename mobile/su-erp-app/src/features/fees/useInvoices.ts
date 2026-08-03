import type { RazorpayOrder, RazorpayProof } from '@api-types/index';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { createInvoiceOrder, fetchInvoices, forgetInvoiceKey, payInvoice } from '@/lib/api/finance';
import { authenticate } from '@/lib/device/biometrics';

import type { CheckoutResult } from '../payments/RazorpayCheckout';
import { isUnconfiguredGateway } from '../payments/usePayment';

export const INVOICES_KEY = ['finance', 'invoices'];

export function useInvoices() {
  return useQuery({ queryKey: INVOICES_KEY, queryFn: fetchInvoices });
}

/** Thrown when the student dismisses the biometric prompt or the widget. */
export class PaymentCancelled extends Error {
  constructor() {
    super('Payment cancelled.');
    this.name = 'PaymentCancelled';
  }
}

export function usePayInvoice(
  runCheckout: (order: RazorpayOrder, description: string) => Promise<CheckoutResult>,
) {
  const client = useQueryClient();

  return useMutation({
    mutationFn: async ({ invoiceId, purpose }: { invoiceId: string; purpose: string }) => {
      const approved = await authenticate('Confirm your fee payment');
      if (!approved) throw new PaymentCancelled();

      // No credentials on the server means no widget to open — the backend's
      // simulated gateway settles it instead.
      let order: RazorpayOrder | null = null;
      try {
        order = await createInvoiceOrder(invoiceId);
      } catch (error) {
        if (!isUnconfiguredGateway(error)) throw error;
      }

      let proof: RazorpayProof | undefined;

      if (order) {
        const result = await runCheckout(order, purpose);

        if (result.type === 'cancelled') throw new PaymentCancelled();
        if (result.type === 'failed') throw new Error(result.message ?? 'Payment failed.');

        proof = result.proof;
      }

      return payInvoice(invoiceId, proof);
    },

    onSuccess: (_data, { invoiceId }) => {
      // Settled, so the next payment against this invoice is a new one and
      // must not reuse the retired key.
      forgetInvoiceKey(invoiceId);
      void client.invalidateQueries({ queryKey: INVOICES_KEY });
    },
  });
}
