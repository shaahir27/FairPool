import { renderHook } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { useCountdown } from "../src/shared/lib/motion";

afterEach(() => vi.useRealTimers());

it("does not infer expiry without a server clock", () => {
  const { result } = renderHook(() => useCountdown("2026-11-10T00:00:00Z", undefined));
  expect(result.current.expired).toBe(false);
  expect(result.current.label).toBe("");
});

it.each([
  [6 * 86400 + 2 * 3600, "6d 2h"],
  [2 * 3600 + 5 * 60, "2h 5m"],
  [13 * 60, "13:00"],
])("formats a server-derived %i second window readably", (seconds, label) => {
  vi.useFakeTimers();
  const start = "2026-11-10T00:00:00Z";
  const end = new Date(Date.parse(start) + seconds * 1000).toISOString();
  const { result } = renderHook(() => useCountdown(end, start));
  expect(result.current.label).toBe(label);
});
