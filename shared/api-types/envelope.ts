/** Every service wraps responses in this shape — see suerp_common/envelope.py. */
export interface ApiEnvelope<T> {
  success: boolean;
  data: T | null;
  message: string;
  errors: unknown;
}

/** List endpoints wrap results in this — see suerp_common StandardPagination. */
export interface Paginated<T> {
  results: T[];
  count: number;
  page: number;
  num_pages: number;
}
