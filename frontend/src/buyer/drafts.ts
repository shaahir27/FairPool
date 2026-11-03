/**
 * The one short-lived fact a buyer carries between the Discover screen and the pool lobby.
 *
 * A confirmed intake request is a server row the join consumes by id, and the lobby is a
 * separate screen: the id has to survive the navigation, so it sits in `sessionStorage`
 * exactly as the CSRF token and the signup draft do — a reload inside the session keeps
 * working, a closed tab loses it, and the stored value is an id and nothing else.
 *
 * The entry receipt is deliberately *not* kept here. `GET /api/v1/pools/{pool_id}/entries/me`
 * returns the signed receipt the join issued (CR-9), so the server is the source and a
 * browser copy would only be a second, staler truth.
 */
const PENDING_KEY = "fairpool.entry.pending";

function read(poolId: string): unknown {
  try {
    const raw = sessionStorage.getItem(`${PENDING_KEY}.${poolId}`);
    return raw ? JSON.parse(raw) : null;
  } catch {
    // Storage can be unavailable (private modes) and a stored value can be corrupt.
    return null;
  }
}

export function rememberPendingRequest(poolId: string, confirmedRequestId: string): void {
  try {
    sessionStorage.setItem(`${PENDING_KEY}.${poolId}`, JSON.stringify(confirmedRequestId));
  } catch {
    // An unwritable draft never blocks the buyer's action; the server is the truth.
  }
}

/** The confirmed request this browser is about to join with, or `null`. */
export function readPendingRequest(poolId: string): string | null {
  const value = read(poolId);
  return typeof value === "string" && value.length > 0 ? value : null;
}

export function clearPendingRequest(poolId: string): void {
  try {
    sessionStorage.removeItem(`${PENDING_KEY}.${poolId}`);
  } catch {
    // Nothing to clean up when storage is unavailable.
  }
}
