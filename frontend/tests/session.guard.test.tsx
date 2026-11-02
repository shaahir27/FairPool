import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

// One stub for the file: openapi-fetch captures `fetch` when the client is
// created, so the status has to be read at call time, not rebound per test.
let status = 200;
let meCalls = 0;

beforeAll(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => {
      meCalls += 1;
      return new Response("{}", { status, headers: { "content-type": "application/json" } });
    }),
  );
});

beforeEach(() => {
  meCalls = 0;
});

async function renderAt(path: string, nextStatus: number) {
  status = nextStatus;
  const { AppRoutes } = await import("../src/App");
  const { resetSessionCache } = await import("../src/shared");
  // Unknown session, like a cold browser: the guard must ask the server.
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
    await renderAt("/orders", 401);

    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Sign in" })).toBeInTheDocument(),
    );
    expect(screen.queryByRole("heading", { name: "Orders" })).toBeNull();
  });

  it("renders the protected route while the session cookie is still valid", async () => {
    await renderAt("/orders", 200);

    await waitFor(() => expect(screen.getByRole("heading", { name: "Orders" })).toBeInTheDocument());
  });

  it("never asks the server on the login page itself", async () => {
    await renderAt("/login", 401);

    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Sign in" })).toBeInTheDocument(),
    );
    expect(meCalls).toBe(0);
  });
});
