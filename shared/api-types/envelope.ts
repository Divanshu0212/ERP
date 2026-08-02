/** Every service wraps responses in this shape — see suerp_common/envelope.py. */
export interface ApiEnvelope<T> {
  success: boolean;
  data: T | null;
  message: string;
  errors: unknown;
}
