import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

import { resetSessionCache } from "../src/shared/lib/session";

afterEach(() => {
  cleanup();
  resetSessionCache();
});
