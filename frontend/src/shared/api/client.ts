import createClient from "openapi-fetch";

import { getCsrfToken } from "../lib/csrf";

import type { components, paths } from "./schema";

const configuredBaseUrl = import.meta.env.VITE_API_BASE_URL?.trim();

/** Vite dev proxy target in `.env.example`; the browser talks to the API directly. */
export const API_BASE_URL =
  configuredBaseUrl && configuredBaseUrl.length > 0
    ? configuredBaseUrl
    : "http://localhost:8000";

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

export type ApiPaths = paths;
export type ApiComponents = components;
