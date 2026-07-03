// Helpers for reading paginated list envelopes.
//
// Gateway list endpoints may return either a bare array or a paginated wrapper
// like `{ items: [...], total: N }` (or `{ results, count }`). These helpers
// normalise both shapes so callers can just read `items` / `total`.

/** Extract the list of items from a list-endpoint payload. */
export function listItems<T = unknown>(data: unknown): T[] {
  if (Array.isArray(data)) return data as T[];
  if (data && typeof data === "object") {
    const rec = data as Record<string, unknown>;
    for (const key of ["items", "results", "data"]) {
      if (Array.isArray(rec[key])) return rec[key] as T[];
    }
  }
  return [];
}

/** Extract the total count from a list-endpoint payload, falling back to length. */
export function listTotal(data: unknown): number {
  if (data && typeof data === "object" && !Array.isArray(data)) {
    const rec = data as Record<string, unknown>;
    for (const key of ["total", "count", "total_count"]) {
      if (typeof rec[key] === "number") return rec[key] as number;
    }
  }
  return listItems(data).length;
}
