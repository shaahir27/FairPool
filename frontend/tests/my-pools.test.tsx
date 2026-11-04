import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const transport = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("../src/shared/api/client", () => ({
  api: { GET: transport.get, POST: transport.post },
  API_BASE_URL: "http://localhost:8000",
}));

// Most tests need only to know that the offer was embedded; one test swaps in the
// real checkout to prove its countdown uses the server's clock.
const checkoutStub = vi.hoisted(() => ({ real: false }));
vi.mock("../src/checkout", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/checkout")>();
  return {
    ...actual,
    OfferCheckout: (props: { buyerOrderId: string; onChanged?: () => void }) =>
      checkoutStub.real ? (
        <actual.OfferCheckout {...props} />
      ) : (
        <div data-testid="offer-checkout">
          Checkout for {props.buyerOrderId}
          {props.onChanged ? (
            <button type="button" onClick={props.onChanged}>
              Simulate approval
            </button>
          ) : null}
        </div>
      ),
  };
});

import { MyPoolsPage } from "../src/buyer/my-pools/MyPoolsPage";
import { resetBuyerPrefetch } from "../src/buyer/prefetch";
import { resetSessionCache } from "../src/shared";

const offerEntry = {
  entry_id: "entry-offer",
  pool_id: "pool-offer",
  entry_status: "ELIGIBLE",
  allocation: { status: "SEATED", zone_id: "US-EAST", rank: 1, lot_id: "lot-one", waitlist_position: null },
  offer: { buyer_order_id: "order-one", status: "OFFERED", offer_expires_at: "2026-11-02T10:15:00Z" },
};

const waitlistEntry = {
  entry_id: "entry-wait",
  pool_id: "pool-wait",
  entry_status: "ELIGIBLE",
  allocation: { status: "WAITLISTED", zone_id: "US-EAST", rank: 5, lot_id: "lot-one", waitlist_position: 3 },
  offer: null,
};

const pendingEntry = {
  entry_id: "entry-pending",
  pool_id: "pool-pending",
  entry_status: "SUBMITTED",
  allocation: null,
  offer: null,
};

const pricedOutEntry = {
  entry_id: "entry-priced",
  pool_id: "pool-priced",
  entry_status: "ELIGIBLE",
  allocation: { status: "PRICED_OUT", zone_id: "US-EAST", rank: 4, lot_id: "lot-two", waitlist_position: null },
  offer: null,
};

const capturedEntry = {
  entry_id: "entry-captured",
  pool_id: "pool-captured",
  entry_status: "ELIGIBLE",
  allocation: { status: "SEATED", zone_id: "US-EAST", rank: 1, lot_id: "lot-one", waitlist_position: null },
  offer: { buyer_order_id: "order-captured", status: "CAPTURED", offer_expires_at: "2026-11-02T10:15:00Z" },
};

const offerResponse = {
  buyer_order_id: "order-one",
  status: "OFFERED",
  merchant: { display_name: "Demo Merchant Alpha" },
  product: { title: "27-inch 4K monitor", variant: "Black", condition: "NEW", bundle_contents: ["Monitor", "Stand"] },
  terms: { delivery_sla_days: 7, returns_days: 30 },
  totals: { item_cents: 48000, shipping_cents: 1000, tax_cents: 900, total_cents: 49900, cap_cents: 60000 },
  offer_expires_at: "2026-11-02T10:15:00Z",
  offer_started_at: "2026-11-02T10:00:00Z",
  server_now: "2026-11-02T10:02:00Z",
  pool_id: "pool-offer",
  pool_title: "Monitor pool",
  notices: {
    hold: "A hold is placed only after approval.",
    lots_may_differ: "Separate lots may have different prices.",
    fallback: null,
  },
};

function show() {
  return render(
    <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <MyPoolsPage />
    </MemoryRouter>,
  );
}

function respondWithEntries(items: unknown[]) {
  transport.get.mockImplementation(async (path: string) => {
    if (path === "/api/v1/me/entries") return { data: { items } };
    if (path === "/api/v1/me/addresses") return { data: { addresses: [] } };
    if (path === "/api/v1/offers/{buyer_order_id}") return { data: offerResponse };
    return { data: null };
  });
}

beforeEach(() => {
  resetBuyerPrefetch();
  checkoutStub.real = false;
  transport.get.mockReset();
  transport.post.mockReset();
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe("My Pools grouping", () => {
  it("groups entries into pending, waitlist and action required", async () => {
    respondWithEntries([pendingEntry, waitlistEntry, offerEntry]);
    show();

    const pending = await screen.findByRole("region", { name: "Pending" });
    const waitlist = screen.getByRole("region", { name: "Waitlist" });
    const action = screen.getByRole("region", { name: "Action required" });

    expect(within(pending).getByText("No seat allocation yet.")).toBeInTheDocument();
    expect(within(waitlist).getByText("Waitlisted, position #3")).toBeInTheDocument();
    expect(within(action).getByTestId("offer-checkout")).toHaveTextContent("order-one");
    expect(within(pending).queryByTestId("offer-checkout")).not.toBeInTheDocument();
    expect(within(waitlist).queryByTestId("offer-checkout")).not.toBeInTheDocument();
  });

  it("keeps a priced-out entry in pending and labels it from the API status", async () => {
    respondWithEntries([pricedOutEntry]);
    show();

    const pending = await screen.findByRole("region", { name: "Pending" });
    expect(within(pending).getByText("PRICED_OUT")).toBeInTheDocument();
    expect(within(pending).getByText("Priced out of this lot. No seat was allocated to this entry.")).toBeInTheDocument();
    const waitlist = screen.getByRole("region", { name: "Waitlist" });
    expect(within(waitlist).getByText("No entries are on a waitlist.")).toBeInTheDocument();
  });

  it("falls back to the allocation rank when no waitlist position is returned", async () => {
    respondWithEntries([{ ...waitlistEntry, allocation: { ...waitlistEntry.allocation, waitlist_position: null } }]);
    show();

    const waitlist = await screen.findByRole("region", { name: "Waitlist" });
    expect(within(waitlist).getByText("Waitlisted, position #5")).toBeInTheDocument();
  });

  it("treats an offer past approval as a line linking to its order, not an action", async () => {
    respondWithEntries([capturedEntry]);
    show();

    const pending = await screen.findByRole("region", { name: "Pending" });
    const action = screen.getByRole("region", { name: "Action required" });

    expect(within(action).getByText("No offers are waiting for you.")).toBeInTheDocument();
    expect(within(action).queryByTestId("offer-checkout")).not.toBeInTheDocument();
    expect(within(pending).getByText("Payment completed")).toBeInTheDocument();
    expect(within(pending).getByRole("link", { name: "Open order for order-captured" })).toHaveAttribute(
      "href",
      "/orders/order-captured",
    );
    expect(within(pending).queryByTestId("offer-checkout")).not.toBeInTheDocument();
  });

  it("links every entry to its pool lobby by name", async () => {
    respondWithEntries([pendingEntry, waitlistEntry]);
    show();

    const pending = await screen.findByRole("region", { name: "Pending" });
    const waitlist = screen.getByRole("region", { name: "Waitlist" });
    expect(within(pending).getByRole("link", { name: "Open pool lobby for pool-pending" })).toHaveAttribute(
      "href",
      "/pools/pool-pending",
    );
    expect(within(waitlist).getByRole("link", { name: "Open pool lobby for pool-wait" })).toHaveAttribute(
      "href",
      "/pools/pool-wait",
    );
  });

  it("renders the offer countdown from the server's clock, not the device's", async () => {
    checkoutStub.real = true;
    vi.spyOn(Date, "now").mockReturnValue(Date.parse("2026-11-03T10:00:00Z"));
    respondWithEntries([offerEntry]);
    show();

    expect(await screen.findByText("13:00")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Continue to PayPal/ })).toBeEnabled();
    expect(screen.getByRole("link", { name: /Back to your pool/ })).toHaveAttribute("href", "/pools/pool-offer");
  });
});

describe("My Pools states", () => {
  it("shows a calm empty state when the buyer has no entries", async () => {
    respondWithEntries([]);
    show();

    expect(await screen.findByRole("heading", { name: "No entries yet" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Find an open pool" })).toHaveAttribute("href", "/discover");
    expect(screen.queryByRole("region", { name: "Pending" })).not.toBeInTheDocument();
  });

  it("keeps the page usable after a failed load and retries", async () => {
    transport.get.mockRejectedValueOnce(new TypeError("network unavailable")).mockResolvedValueOnce({ data: { items: [pendingEntry] } });
    show();

    expect(await screen.findByRole("alert")).toHaveTextContent(/connection|try again/i);
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("region", { name: "Pending" })).toBeInTheDocument();
  });

  it("reloads the entry list when an inline approval changes the offer", async () => {
    respondWithEntries([offerEntry]);
    show();

    await screen.findByTestId("offer-checkout");
    fireEvent.click(screen.getByRole("button", { name: "Simulate approval" }));

    await waitFor(() =>
      expect(transport.get.mock.calls.filter(([path]) => path === "/api/v1/me/entries")).toHaveLength(2),
    );
  });

  it("never shows the previous session's cached entries to the next user", async () => {
    respondWithEntries([pendingEntry]);
    const first = show();
    expect(await screen.findByText("pool-pending")).toBeInTheDocument();
    first.unmount();

    // What sign-out (and any 401) does: the session ends, so the cached pages go too.
    resetSessionCache("out");

    respondWithEntries([waitlistEntry]);
    show();
    const waitlist = await screen.findByRole("region", { name: "Waitlist" });
    expect(within(waitlist).getByText("Waitlisted, position #3")).toBeInTheDocument();
    expect(screen.queryByText("pool-pending")).not.toBeInTheDocument();
    expect(transport.get.mock.calls.filter(([path]) => path === "/api/v1/me/entries")).toHaveLength(2);
  });
});
