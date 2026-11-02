/**
 * Cached result of the one session check, so navigation does not re-ask /me.
 * `null` means "unknown, ask the server"; the login form resets it.
 */
export type SessionState = "in" | "out" | null;

let sessionKnown: SessionState = null;

export function sessionState(): SessionState {
  return sessionKnown;
}

export function resetSessionCache(next: SessionState = null): void {
  sessionKnown = next;
}
