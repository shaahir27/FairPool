import createClient from "openapi-fetch";

import { getCsrfToken, setCsrfToken } from "../lib/csrf";
import { resetSessionCache } from "../lib/session";

import { refreshReads } from "./reads";

import type { components, paths } from "./schema";

const configuredBaseUrl = import.meta.env.VITE_API_BASE_URL?.trim();

/** With no `VITE_API_BASE_URL` the browser calls its own origin: in development that
 * is the Vite proxy, and on the hosted deployment it is the API that serves this build,
 * which keeps the session cookie first-party. */
export const API_BASE_URL =
  configuredBaseUrl && configuredBaseUrl.length > 0
    ? configuredBaseUrl
    : window.location.origin;

/**
 * Typed client for the committed OpenAPI snapshot (frontend/openapi.json).
 * Types are generated; never hand-edit `schema.d.ts`.
 */
export const api = createClient<paths>({
  baseUrl: API_BASE_URL,
  credentials: "include",
});

// deps.py rejects every non-GET without this header; the token arrives at login.
api.use({
  onRequest({ request }) {
    const token = getCsrfToken();
    if (token && !["GET", "HEAD", "OPTIONS"].includes(request.method.toUpperCase())) {
      request.headers.set("X-CSRF-Token", token);
    }
    return request;
  },
});

// A 401 mid-session means the cookie died or was revoked: drop the cached answer so
// the next gated route re-asks /me instead of rendering a screen every call fails.
api.use({
  onResponse({ request, response }) {
    if (response.ok && request.method === "GET" && new URL(request.url).pathname === "/api/v1/me") {
      const token = response.headers.get("X-CSRF-Token");
      if (token) setCsrfToken(token);
    }
    if (response.status === 401) resetSessionCache("out");
    return response;
  },
});

export type ApiPaths = paths;
export type ApiComponents = components;

// Every write invalidates read views, including an uncertain network outcome.
api.use({
  async onResponse({ request }) {
    if (!["GET", "HEAD", "OPTIONS"].includes(request.method)) await refreshReads();
  },
  async onError({ request }) {
    if (!["GET", "HEAD", "OPTIONS"].includes(request.method)) await refreshReads();
  },
});
