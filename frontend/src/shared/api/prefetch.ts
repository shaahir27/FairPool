import { api } from "./client";
import { prefetchRead } from "./reads";

/** Intent only: no bulk download of every portal or of payment/credential URLs. */
export function prefetchWorkspace(to: string): void {
  if (to === "/discover") void prefetchRead("/api/v1/pools?status=OPEN&sort=trending&limit=100", (signal) => api.GET("/api/v1/pools", { signal, params: { query: { status: "OPEN", sort: "trending", limit: 100 } } }), 60_000);
  else if (to === "/my-pools") void prefetchRead("/api/v1/me/entries", (signal) => api.GET("/api/v1/me/entries", { signal }));
  else if (to === "/orders") void prefetchRead("/api/v1/me/orders", (signal) => api.GET("/api/v1/me/orders", { signal }));
  else if (to === "/settings/agents") {
    void prefetchRead("/api/v1/me/delegations", (signal) => api.GET("/api/v1/me/delegations", {signal}));
    void prefetchRead("/api/v1/pools?status=OPEN&limit=100", (signal) => api.GET("/api/v1/pools", {signal, params: {query: {status: "OPEN", limit: 100}}}), 60_000);
  }
  else if (to === "/merchant/developer") void prefetchRead("/api/v1/merchant/api-keys", (signal) => api.GET("/api/v1/merchant/api-keys", {signal}));
  else if (to === "/settings/addresses") void prefetchRead("/api/v1/me/addresses", (signal) => api.GET("/api/v1/me/addresses", { signal }));
  else if (to === "/merchant/demand") void prefetchRead("/api/v1/merchant/lots", (signal) => api.GET("/api/v1/merchant/lots", { signal }));
  else if (to === "/merchant/bids" || to === "/merchant/fulfillment") void prefetchRead("/api/v1/merchant/bids", (signal) => api.GET("/api/v1/merchant/bids", { signal }));
  else if (to === "/merchant/profile") void prefetchRead("/api/v1/merchant/profile", (signal) => api.GET("/api/v1/merchant/profile", { signal }));
  else if (to === "/ops" || to === "/ops/lots") void prefetchRead("/api/v1/admin/alerts", (signal) => api.GET("/api/v1/admin/alerts", { signal }));
  else if (to === "/ops/recovery") void prefetchRead("/api/v1/admin/webhooks/dead-letter", (signal) => api.GET("/api/v1/admin/webhooks/dead-letter", { signal }));
  else {
    const pool = /^\/pools\/([^/?#]+)$/.exec(to);
    if (pool) {
      const id = pool[1]!;
      void prefetchRead(`/api/v1/pools/${id}`, (signal) => api.GET("/api/v1/pools/{pool_id}", { signal, params: { path: { pool_id: id } } }));
    }
  }
}
