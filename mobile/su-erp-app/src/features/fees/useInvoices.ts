import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { fetchInvoices, forgetIdempotencyKey, payInvoice } from '@/lib/api/finance';
import { authenticate } from '@/lib/device/biometrics';

export const INVOICES_KEY = ['finance', 'invoices'];

export function useInvoices() {
  return useQuery({ queryKey: INVOICES_KEY, queryFn: fetchInvoices });
}

/** Thrown when the student dismisses the biometric prompt — not an error to shout about. */
export class PaymentCancelled extends Error {
  constructor() {
    super('Payment cancelled.');
    this.name = 'PaymentCancelled';
  }
}

export function usePayInvoice() {
  const client = useQueryClient();

  return useMutation({
    mutationFn: async (invoiceId: string) => {
      const approved = await authenticate('Confirm your fee payment');
      if (!approved) throw new PaymentCancelled();

      return payInvoice(invoiceId);
    },

    onSuccess: (_data, invoiceId) => {
      // The invoice is settled, so the next payment against this id would be
      // a genuinely new one and must not reuse the retired key.
      forgetIdempotencyKey(invoiceId);
      void client.invalidateQueries({ queryKey: INVOICES_KEY });
    },
  });
}
