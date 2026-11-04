import { api } from "../shared";

// Short on purpose: a hover pays for the click, but a money status never lags for long.
const TTL_MS = 3_000;
const cache = new Map<string, { at: number; promise: Promise<unknown> }>();

function once<T>(key: string, run: () => Promise<T>, force = false): Promise<T> {
  const hit = cache.get(key);
  if (!force && hit && Date.now() - hit.at < TTL_MS) return hit.promise as Promise<T>;
  const promise = run();
  cache.set(key, { at: Date.now(), promise });
  promise.catch(() => {
    if (cache.get(key)?.promise === promise) cache.delete(key);
  });
  return promise;
}

/** Same request the page makes, deduped and held briefly so a hover pays for the click. */
export const loadEntries = (force = false) =>
  once("entries", () => api.GET("/api/v1/me/entries"), force);

export const loadOrders = (force = false) =>
  once("orders", () => api.GET("/api/v1/me/orders"), force);

/** Tests and sign-out should not inherit another session's page. */
export function resetBuyerPrefetch(): void {
  cache.clear();
}

// Signing out, or any 401, ends the session the cached pages belonged to; the
// event name mirrors shared/lib/session.ts without importing across the boundary.
window.addEventListener("fairpool:session-ended", resetBuyerPrefetch);

/** Warm the code and the data for a buyer tab the moment it is pointed at. */
export function prefetchBuyer(to: string): void {
  if (to === "/my-pools") {
    void loadEntries();
    void import("./my-pools/MyPoolsPage").catch(() => {});
    void import("../checkout").catch(() => {});
    return;
  }
  if (to === "/orders") {
    void loadOrders();
    void import("./orders/OrdersPage").catch(() => {});
  }
}
