/**
 * Stable idempotency keys, held per operation for the life of the process.
 *
 * A fresh key on every attempt defeats the mechanism in exactly the case it
 * exists for: the backend deduplicates on (resource, key), so a student
 * retrying after a timeout would send a new key and be charged twice, or claim
 * a second seat. Reusing the key means the retry returns the first outcome.
 */
const keys = new Map<string, string>();

export function uuidv4(): string {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

export function idempotencyKeyFor(scope: string): string {
  const existing = keys.get(scope);
  if (existing) return existing;

  const key = uuidv4();
  keys.set(scope, key);
  return key;
}

/** Drops a settled operation's key so a later, genuinely new one is distinct. */
export function forgetIdempotencyKey(scope: string): void {
  keys.delete(scope);
}
