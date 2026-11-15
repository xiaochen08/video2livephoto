let n = 0
/** Client-generated idempotency key for one user intent (reused on retries of the same intent). */
export function requestId(prefix = 'req'): string {
  n = (n + 1) % 1_000_000
  return `${prefix}-${Date.now().toString(36)}-${n.toString(36)}-${Math.random().toString(36).slice(2, 6)}`
}
