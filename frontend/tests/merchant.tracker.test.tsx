import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const transport = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), remove: vi.fn() }));
vi.mock("../src/shared/api/client", () => ({
  api: {
    GET: transport.get,
    POST: transport.post,
    PUT: transport.put,
    DELETE: transport.remove,
  },
  API_BASE_URL: "http://localhost:8000",
}));

import { bidGroup, trackerOf } from "../src/merchant/bids/tracker";
import { BidsPage } from "../src/merchant/bids/BidsPage";

function bid(overrides: Record<string, unknown> = {}) {
  return {
    bid_id: "bid-a",
    lot_id: "lot-a",
    status: "CONFIRMED",
    current_revision: 1,
    structured: { product_key: "monitor-27-4k" },
    flags: [],
    reject_reason: null,
    ...overrides,
  };
}

function progress(overrides: Record<string, unknown> = {}) {
  return {
    lot_id: "lot-b",
    status: "CHECKOUT_OPEN",
    seats: 3,
    moq: 3,
    holds_placed: 2,
    captures_completed: 0,
    refills_offered: 1,
    counts: { OFFERED: 1, AUTHORIZED: 2 },
    fund_deadline_at: "2026-11-10T18:00:00Z",
    labels: ["SANDBOX", "FALLBACK: single stand-in seller"],
    ...overrides,
  };
}

function show() {
  return render(
    <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }} initialEntries={["/merchant/bids"]}>
      <BidsPage />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  transport.get.mockReset();
  transport.post.mockReset();
  transport.put.mockReset();
  transport.remove.mockReset();
});

describe("bid grouping", () => {
  it("files every bid status into exactly one console section", () => {
    expect(bidGroup("DRAFT")).toBe("pending");
    expect(bidGroup("PROPOSED")).toBe("pending");
    expect(bidGroup("CONFIRMED")).toBe("pending");
    expect(bidGroup("FLAGGED")).toBe("pending");
    expect(bidGroup("ELIGIBLE")).toBe("pending");
    expect(bidGroup("AWARDED")).toBe("checkout");
    expect(bidGroup("LOST")).toBe("lost");
    expect(bidGroup("REJECTED")).toBe("lost");
  });

  it("keeps an unknown status visible rather than dropping the bid", () => {
    expect(bidGroup("SOMETHING_NEW")).toBe("pending");
  });
});

describe("checkout tracker math", () => {
  it("counts holds against the MOQ until captures begin", () => {
    const tracker = trackerOf({ moq: 3, holds_placed: 2, captures_completed: 0 });
    expect(tracker.phase).toBe("holds");
    expect(tracker.primary).toBe(2);
    expect(tracker.target).toBe(3);
    expect(tracker.remaining).toBe(1);
    expect(tracker.met).toBe(false);
    expect(tracker.fraction).toBeCloseTo(2 / 3);
  });

  it("counts captures against the MOQ once any capture completes, ignoring extra holds", () => {
    const tracker = trackerOf({ moq: 2, holds_placed: 5, captures_completed: 2 });
    expect(tracker.phase).toBe("captures");
    expect(tracker.primary).toBe(2);
    expect(tracker.remaining).toBe(0);
    expect(tracker.met).toBe(true);
    expect(tracker.fraction).toBe(1);
  });

  it("never claims a met minimum when no minimum is published", () => {
    const tracker = trackerOf({ moq: 0, holds_placed: 0, captures_completed: 0 });
    expect(tracker.fraction).toBe(0);
    expect(tracker.met).toBe(false);
  });
});

describe("Active Bids", () => {
  it("groups pending, checkout and lost bids and shows the honest reasons", async () => {
    transport.get.mockImplementation((path: string) => {
      if (path === "/api/v1/merchant/bids") {
        return Promise.resolve({
          data: {
            items: [
              bid({ bid_id: "bid-a", lot_id: "lot-a", status: "CONFIRMED" }),
              bid({ bid_id: "bid-b", lot_id: "lot-b", status: "AWARDED", structured: { product_key: "ceramic-kettle" } }),
              bid({
                bid_id: "bid-c",
                lot_id: "lot-c",
                status: "LOST",
                structured: { product_key: "keyboard" },
                flags: [
                  {
                    code: "LOW_SIMILARITY",
                    severity: "WARNING",
                    field: "product_key",
                    evidence: "The top match was a different product.",
                  },
                ],
              }),
              bid({
                bid_id: "bid-d",
                lot_id: "lot-d",
                status: "REJECTED",
                structured: { product_key: "lamp" },
                reject_reason: "DUPLICATE_PAYER",
              }),
            ],
          },
        });
      }
      if (path === "/api/v1/merchant/lots/{lot_id}/progress") {
        return Promise.resolve({ data: progress() });
      }
      return Promise.resolve({ data: [] });
    });
    show();

    expect(await screen.findByRole("heading", { level: 1, name: "Active Bids" })).toBeInTheDocument();
    const pending = await screen.findByRole("region", { name: "Pending" });
    expect(within(pending).getByText("CONFIRMED")).toBeInTheDocument();
    expect(within(pending).getByText("monitor-27-4k")).toBeInTheDocument();

    const checkout = screen.getByRole("region", { name: "In Checkout" });
    expect(await within(checkout).findByText("2 of 3 seats held or charged")).toBeInTheDocument();
    expect(within(checkout).queryByText(/holds placed/)).not.toBeInTheDocument();
    const refills = within(checkout).getByText("Refills offered").closest("div");
    expect(refills).toHaveTextContent("Refills offered1");
    expect(within(checkout).getByText("FALLBACK: single stand-in seller")).toBeInTheDocument();

    const lost = screen.getByRole("region", { name: "Lost or Failed" });
    expect(within(lost).getByText("DUPLICATE_PAYER")).toBeInTheDocument();
    expect(
      within(lost).getByText(/This PayPal account was already used for another seat in this lot\./),
    ).toBeInTheDocument();
    expect(within(lost).getByText("LOW_SIMILARITY")).toBeInTheDocument();
    expect(within(lost).getByText(/different product/)).toBeInTheDocument();
  });

  it("switches the tracker to captures once captures begin", async () => {
    transport.get.mockImplementation((path: string) => {
      if (path === "/api/v1/merchant/bids") {
        return Promise.resolve({
          data: { items: [bid({ bid_id: "bid-b", lot_id: "lot-b", status: "AWARDED" })] },
        });
      }
      if (path === "/api/v1/merchant/lots/{lot_id}/progress") {
        return Promise.resolve({
          data: progress({ moq: 2, holds_placed: 3, captures_completed: 2, refills_offered: 0 }),
        });
      }
      return Promise.resolve({ data: [] });
    });
    show();

    const checkout = await screen.findByRole("region", { name: "In Checkout" });
    expect(await within(checkout).findByText("2 of 2 captures completed")).toBeInTheDocument();
    expect(within(checkout).queryByText(/holds placed/)).not.toBeInTheDocument();
  });

  it("shows an honest empty state when this merchant has no bids", async () => {
    transport.get.mockResolvedValue({ data: { items: [] } });
    show();
    expect(await screen.findByText("No bids from your merchant account yet.")).toBeInTheDocument();
  });
});

it("focuses a merchant bid group without refetching the bid list", async () => {
  transport.get.mockResolvedValue({data: {items: [bid({status: "CONFIRMED"}), bid({bid_id: "lost", status: "LOST"})]}});
  show();
  fireEvent.click(await screen.findByRole("button", {name: "Pending 1"}));
  expect(screen.getByRole("region", {name: "Pending"})).toBeInTheDocument();
  expect(screen.queryByRole("region", {name: "Lost or Failed"})).toBeNull();
  expect(transport.get.mock.calls.filter(([path]) => path === "/api/v1/merchant/bids")).toHaveLength(1);
});
