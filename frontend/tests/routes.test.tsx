import { lazy, Suspense } from "react";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

const transport = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("../src/shared/api/client", () => ({
  api: { GET: transport.get, POST: transport.post },
  API_BASE_URL: "http://localhost:8000",
}));

import { resetSessionCache, setAccount } from "../src/shared";

import { AppRoutes, RouteLoadBoundary } from "../src/App";

function renderAt(path: string) {
  return render(
    <MemoryRouter
      initialEntries={[path]}
      future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
    >
      <AppRoutes />
    </MemoryRouter>,
  );
}

beforeAll(() => {
  // The guard reads one session state; these tests are about the routes.
  resetSessionCache("in");
});

beforeEach(() => {
  resetSessionCache("in");
  setAccount({ display_name: "Test Buyer", role: "buyer", paypal_linked: false });
  sessionStorage.clear();
  transport.get.mockReset().mockResolvedValue({
    data: [
      {
        pool_id: "pool-one",
        title: "27-inch 4K monitor",
        status: "OPEN",
        mode: "LIVE_SANDBOX",
        product_key: "monitor-27-4k",
        condition: "NEW",
        variant: "black",
        zone_ids: ["US-EAST"],
        seats: 12,
        min_seats: 6,
        close_at: "2026-11-05T18:00:00Z",
      },
    ],
  });
  transport.post.mockReset();
});

describe("route smoke", () => {
  it("offers recovery when a page download fails", async () => {
    const originalError = vi.spyOn(console, "error").mockImplementation(() => {});
    const FailedPage = lazy(() => Promise.reject(new Error("Unavailable route chunk")));
    try {
      render(<RouteLoadBoundary><Suspense fallback={<p>Loading</p>}><FailedPage /></Suspense></RouteLoadBoundary>);
      expect(await screen.findByRole("alert")).toHaveTextContent("This page could not be loaded");
      expect(screen.getByRole("button", { name: "Reload page" })).toBeEnabled();
    } finally {
      originalError.mockRestore();
    }
  });
  it("renders the real Discover and Join screen at /discover", async () => {
    renderAt("/discover");

    expect(
      await screen.findByRole("heading", { level: 1, name: "Open pools" }),
    ).toBeInTheDocument();
    // T06B05 replaced this placeholder: the prompt bar and the fixed badge are the screen.
    expect(
      screen.getByLabelText("What are you looking for and what is your max price?"),
    ).toBeInTheDocument();
    expect(
      await screen.findByText(
        "$0 to join. No hold until a merchant meets your price and you approve.",
        undefined,
        { timeout: 2000 },
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Buyer workspace tabs" })).toBeInTheDocument();
    expect(screen.getByText("SANDBOX")).toBeInTheDocument();
    expect(transport.get).toHaveBeenCalled();
  });

  it("renders the pool lobby at /pools/:poolId", async () => {
    transport.get.mockImplementation((path: string) => {
      if (path === "/api/v1/pools/{pool_id}") {
        return Promise.resolve({
          data: {
            pool_id: "pool-one",
            title: "27-inch 4K monitor",
            status: "OPEN",
            mode: "LIVE_SANDBOX",
            product_key: "monitor-27-4k",
            condition: "NEW",
            zone_ids: ["US-EAST"],
            seats: 12,
            min_seats: 6,
            close_at: "2026-11-05T18:00:00Z",
            template: { zones: [{ zone_id: "US-EAST", regions: ["NY"] }] },
            lot_plan: [],
            timeline: {},
            rules_hash: "a".repeat(64),
          },
        });
      }
      return Promise.resolve({ error: { error: { code: "NOT_FOUND" } } });
    });
    renderAt("/pools/pool-one");

    expect(
      await screen.findByRole("heading", { level: 1, name: "27-inch 4K monitor" }),
    ).toBeInTheDocument();
    expect(screen.getByText("How this pool runs")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Confirm and join" })).toBeEnabled();
  });

  it("renders the merchant Demand Board placeholder", async () => {
    setAccount({ display_name: "Test Merchant", role: "merchant", paypal_linked: false });
    renderAt("/merchant/demand");

    expect(await screen.findByRole("heading", { level: 1, name: "Demand Board" })).toBeInTheDocument();
    expect(screen.getByText("T08B01")).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Merchant workspace tabs" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Fulfillment" })).toBeInTheDocument();
  });
});
