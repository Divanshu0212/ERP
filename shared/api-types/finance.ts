/** DecimalField values arrive as strings — never do math on them directly. */
export type Decimal = string;

export type InvoiceStatus = 'pending' | 'paid' | 'failed' | 'cancelled';

/** billing/serializers.py InvoiceSerializer. */
export interface Invoice {
  id: string;
  student_user_code: string;
  amount: Decimal;
  purpose: string;
  status: InvoiceStatus;
  created_at: string;
}

export interface PayRequest {
  invoice_id: string;
  idempotency_key: string;
  razorpay_order_id?: string;
  razorpay_payment_id?: string;
  razorpay_signature?: string;
}

/**
 * What a checkout widget needs to open. Returned by
 * POST /finance/invoices/{id}/razorpay-order and POST /orders/checkout.
 *
 * When Razorpay is not configured on the server, canteen checkout returns a
 * simulated order with an `SIM-` prefixed id and an empty key_id, so the flow
 * can be exercised end-to-end without real credentials.
 */
export interface RazorpayOrder {
  order_id: string;
  amount: string;
  currency: string;
  key_id: string;
}

/** Proof of payment handed back by the Razorpay checkout widget. */
export interface RazorpayProof {
  razorpay_order_id: string;
  razorpay_payment_id: string;
  razorpay_signature: string;
}
