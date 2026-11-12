/**
 * CSRF for every mutating call (deps.py rejects one without it).
 *
 * Login supplies the token; authenticated GET /me restores it in a new tab.
 * Memory plus sessionStorage keeps it tab-scoped and supports reloads.
 */
const STORAGE_KEY = "fairpool.csrf";

let current: string | null = null;

export function setCsrfToken(token: string | null): void {
  current = token;
  try {
    if (token) {
      sessionStorage.setItem(STORAGE_KEY, token);
    } else {
      sessionStorage.removeItem(STORAGE_KEY);
    }
  } catch {
    // Storage can be unavailable in private modes; the in-memory token still works.
  }
}

export function getCsrfToken(): string | null {
  if (current) {
    return current;
  }
  try {
    current = sessionStorage.getItem(STORAGE_KEY);
  } catch {
    current = null;
  }
  return current;
}
