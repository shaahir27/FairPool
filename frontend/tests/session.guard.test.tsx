import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

// One stub for the file: openapi-fetch captures `fetch` when the client is
// created, so the behaviour has to be read at call time, not rebound per test.
type Behavior = "in" | "out" | "boom" | "error";
let behavior: Behavior = "in";
let meCalls = 0;

beforeAll(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => {
      meCalls += 1;
      if (behavior === "boom") throw new TypeError("Failed to fetch");
      const status = behavior === "in" ? 200 : behavior === "error" ? 503 : 401;
      return new Response(JSON.stringify({ display_name: "Test Buyer", role: "buyer", paypal_linked: false }), { status, headers: { "content-type": "application/json" } });
    }),
  );
});

beforeEach(() => {
  meCalls = 0;
});

async function renderAt(path: string, next: Behavior) {
  behavior = next;
  const { AppRoutes } = await import("../src/App");
  const { resetSessionCache } = await import("../src/shared");
  // Unknown session, like a cold browser: the guard has to ask the server.
  resetSessionCache();
  render(
    <MemoryRouter
      initialEntries={[path]}
      future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
    >
      <AppRoutes />
    </MemoryRouter>,
  );
}

describe("session guard", () => {
  it("sends a signed-out visit to a protected route to the login page", async () => {
    await renderAt("/orders", "out");

    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Sign in" })).toBeInTheDocument(),
    );
    expect(screen.queryByRole("heading", { name: "Orders" })).toBeNull();
  });

  it("renders the protected route while the session cookie is still valid", async () => {
    await renderAt("/orders", "in");

    await waitFor(() => expect(screen.getByRole("heading", { name: "Orders" })).toBeInTheDocument());
  });

  it("keeps the login page public and never loops through the guard", async () => {
    await renderAt("/login", "out");

    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Sign in" })).toBeInTheDocument(),
    );
    expect(meCalls).toBe(0);
  });

  it("reports an unknown status when the server cannot be reached, then recovers", async () => {
    await renderAt("/orders", "boom");

    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Cannot reach FairPool" })).toBeInTheDocument(),
    );
    expect(screen.queryByRole("heading", { name: "Sign in" })).toBeNull();

    behavior = "in";
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Orders" })).toBeInTheDocument(),
    );
  });

  it("reads a server error as an unknown status, never as signed out", async () => {
    await renderAt("/orders", "error");

    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Cannot reach FairPool" })).toBeInTheDocument(),
    );
    expect(screen.queryByRole("heading", { name: "Sign in" })).toBeNull();
  });

  it("drops the cached session when any call answers 401", async () => {
    const { api, resetSessionCache, sessionState } = await import("../src/shared");
    resetSessionCache("in");
    behavior = "out";
    await api.GET("/api/v1/me");

    expect(sessionState()).toBe("out");
  });
});


it("removes a mounted workspace immediately when the session ends", async () => {
  await renderAt("/orders", "in");
  await screen.findByRole("heading", {name: "Orders"});
  const {resetSessionCache} = await import("../src/shared");
  act(() => resetSessionCache("out"));
  expect(await screen.findByRole("heading", {name: "Sign in"})).toBeInTheDocument();
  expect(screen.queryByRole("heading", {name: "Orders"})).toBeNull();
});
