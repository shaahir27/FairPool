/**
 * CSRF for every mutating call (deps.py rejects one without it).
 *
 * The token comes from `POST /auth/login` and lives in memory plus
 * `sessionStorage`, so a reload keeps working but a closed tab does not.
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
