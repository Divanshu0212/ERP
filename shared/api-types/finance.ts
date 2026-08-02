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
}
