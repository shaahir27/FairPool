import { resetReadCache } from "../api/reads";

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

export function workspaceHome(role: string): string | null {
  return role === "admin" ? "/ops" : role === "merchant" ? "/merchant/demand" : role === "buyer" ? "/discover" : null;
}

export function workspaceRole(path: string): string | null {
  const section = path.split(/[/?#]/)[1] ?? "";
  if (section === "ops") return "admin";
  if (section === "merchant") return "merchant";
  return ["discover", "my-pools", "orders", "pools", "settings", "offers", "agents"].includes(section) ? "buyer" : null;
}

/**
 * Announced on the window when a session ends, so the route guard can react to a
 * 401 from any call without polling. A plain event keeps `shared` free of imports
 * from the areas it serves.
 */
export const SESSION_ENDED_EVENT = "fairpool:session-ended";

let sessionKnown: SessionState = null;
let account: Account | null = null;
const accountListeners = new Set<() => void>();

export function subscribeAccount(listener: () => void): () => void {
  accountListeners.add(listener);
  return () => { accountListeners.delete(listener); };
}

export function sessionState(): SessionState {
  return sessionKnown;
}

export function accountState(): Account | null {
  return account;
}

export function setAccount(next: Account | null): void {
  account = next;
  accountListeners.forEach((listener) => listener());
}

export function resetSessionCache(next: SessionState = null): void {
  const hadSession = sessionKnown === "in";
  sessionKnown = next;
  // Only a signed-in session leaves data behind worth clearing. On a public page the
  // first /me probe answers 401 for every visitor, and clearing then aborts that page's
  // own in-flight public reads, which left the audit page on "Loading" forever.
  if (next !== "in") {
    setAccount(null);
    if (hadSession) resetReadCache();
  }
  if (next === "out" && typeof window !== "undefined") {
    // The guard on a cold visit learns "signed out" only from this signal, so it
    // fires on the first 401 as well; the cache clear above is what needs a session.
    window.dispatchEvent(new Event(SESSION_ENDED_EVENT));
  }
}
