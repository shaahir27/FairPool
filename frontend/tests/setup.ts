import {webcrypto} from "node:crypto";

import "@testing-library/jest-dom/vitest";

// jsdom ships no Web Crypto. Node's implementation is the one Web Crypto API, so the
// audit page's SHA-256 and Ed25519 calls run for real in tests instead of being mocked
// -- a mocked hash would prove nothing about matching the backend's bytes.
if (globalThis.crypto === undefined || globalThis.crypto.subtle === undefined) {
  Object.defineProperty(globalThis, "crypto", {value: webcrypto, configurable: true});
}

import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

import { readClient } from "../src/shared/api/reads";
import { resetSessionCache } from "../src/shared/lib/session";

afterEach(() => {
  cleanup();
  resetSessionCache();
  // A public page no longer clears the cache on a 401, so isolation is explicit here.
  readClient.clear();
});
