import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const transport = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("../src/shared/api/client", () => ({
  api: { GET: transport.get, POST: transport.post },
  API_BASE_URL: "http://localhost:8000",
}));

import { OrdersPage } from "../src/buyer/orders/OrdersPage";
import { resetBuyerPrefetch } from "../src/buyer/prefetch";

const receipt = {
  commitment: "c".repeat(64),
  salt_hex: "s".repeat(64),
  signature: "sig-base64url",
  signed_at: "2026-11-02T10:03:00Z",
};

const orders = [
  { buyer_order_id: "order-paid", lot_id: "lot-a", status: "CAPTURED", total_cents: 49900, receipt },
  { buyer_order_id: "order-progress", lot_id: "lot-b", status: "AUTHORIZING", total_cents: 12345, receipt: null },
  { buyer_order_id: "order-void", lot_id: "lot-a", status: "VOIDED", total_cents: 2500, receipt: null },
  { buyer_order_id: "order-refund", lot_id: "lot-c", status: "REFUNDED", total_cents: 7700, receipt },
  { buyer_order_id: "order-expired", lot_id: "lot-d", status: "EXPIRED", total_cents: 9900, receipt: null },
  { buyer_order_id: "order-declined", lot_id: "lot-e", status: "DECLINED", total_cents: 1500, receipt: null },
];

function show() {
  return render(
    <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <OrdersPage />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  resetBuyerPrefetch();
  transport.get.mockReset();
  transport.post.mockReset();
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe("Orders grouping", () => {
  it("groups orders by their API outcome", async () => {
    transport.get.mockResolvedValue({ data: { items: orders } });
    show();

    const paid = await screen.findByRole("region", { name: "Paid" });
    const progress = screen.getByRole("region", { name: "In progress" });
    const released = screen.getByRole("region", { name: "Released" });
    const closed = screen.getByRole("region", { name: "Not completed" });

    expect(within(paid).getByText("Payment completed")).toBeInTheDocument();
    expect(within(progress).getByText("Confirming the hold")).toBeInTheDocument();
    expect(within(released).getByText("Hold released")).toBeInTheDocument();
    expect(within(released).getByText("Refunded")).toBeInTheDocument();
    expect(within(closed).getByText("Offer expired")).toBeInTheDocument();
    expect(within(closed).getByText("Declined")).toBeInTheDocument();
  });

  it("shows each order's total and the API's raw status beside the label", async () => {
    transport.get.mockResolvedValue({ data: { items: orders } });
    show();

    const paid = await screen.findByRole("region", { name: "Paid" });
    expect(within(paid).getByText("$499.00")).toBeInTheDocument();
    expect(within(paid).getByText("CAPTURED")).toBeInTheDocument();
    const closed = screen.getByRole("region", { name: "Not completed" });
    expect(within(closed).getByText("$99.00")).toBeInTheDocument();
    expect(within(closed).getByText("$15.00")).toBeInTheDocument();
  });

  it("says whether a receipt exists and links to that order by name", async () => {
    transport.get.mockResolvedValue({ data: { items: orders } });
    show();

    const paid = await screen.findByRole("region", { name: "Paid" });
    const progress = screen.getByRole("region", { name: "In progress" });

    expect(within(paid).getByText("Receipt available")).toBeInTheDocument();
    expect(within(paid).getByRole("link", { name: "Open order and receipt for order-paid" })).toHaveAttribute(
      "href",
      "/orders/order-paid",
    );
    expect(within(progress).getByText("No receipt for this order")).toBeInTheDocument();
    expect(within(progress).getByRole("link", { name: "Open order for order-progress" })).toHaveAttribute(
      "href",
      "/orders/order-progress",
    );
  });
});

describe("Orders states", () => {
  it("shows an empty state when there are no orders", async () => {
    transport.get.mockResolvedValue({ data: { items: [] } });
    show();

    expect(await screen.findByRole("heading", { name: "No orders yet" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Find a pool to join" })).toHaveAttribute("href", "/discover");
    expect(screen.queryByRole("region", { name: "Paid" })).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "In progress" })).not.toBeInTheDocument();
  });

  it("keeps the error inside the page and retries the load", async () => {
    transport.get.mockRejectedValueOnce(new TypeError("network unavailable")).mockResolvedValueOnce({ data: { items: [orders[0]] } });
    show();

    expect(await screen.findByText(/We couldn’t load your orders/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    const paid = await screen.findByRole("region", { name: "Paid" });
    expect(within(paid).getByText("$499.00")).toBeInTheDocument();
  });
});
