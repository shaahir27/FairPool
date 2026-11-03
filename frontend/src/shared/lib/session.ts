/**
 * Cached result of the one session check, so navigation does not re-ask /me.
 * `null` means "unknown, ask the server"; the login form resets it.
 */
export type SessionState = "in" | "out" | null;

/**
 * The two facts the workspace shell shows about the signed-in person. `RequireAuth`
 * already asks `/me` once per cold navigation, so the shell reads it from here instead of
 * sending a second request for the same answer.
 */
export interface Account {
  display_name: string;
  role: string;
  paypal_linked: boolean;
}

let sessionKnown: SessionState = null;
let account: Account | null = null;

export function sessionState(): SessionState {
  return sessionKnown;
}

export function accountState(): Account | null {
  return account;
}

export function setAccount(next: Account | null): void {
  account = next;
}

export function resetSessionCache(next: SessionState = null): void {
  sessionKnown = next;
  // A session that is no longer known is no longer evidence about who it belongs to.
  if (next !== "in") account = null;
}
