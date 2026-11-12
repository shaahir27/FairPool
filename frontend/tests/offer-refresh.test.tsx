import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, it, vi } from "vitest";

const transport = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("../src/shared/api/client", () => ({ api: { GET: transport.get, POST: transport.post } }));
// Unit seam for the SDK callback: this test checks form lifetime, not provider execution.
vi.mock("../src/checkout/PayPalButton", () => ({ PayPalButton: ({ onRefresh }: { onRefresh: () => void }) => <button onClick={onRefresh}>Refresh offer state</button> }));

import { OfferCheckout } from "../src/checkout/OfferCheckout";

it("retains edited delivery fields when an SDK-triggered offer refresh fails", async () => {
  let failRefresh = false;
  const offer = {
    buyer_order_id: "offer-refresh", status: "OFFERED", pool_id: "pool-refresh",
    merchant: { display_name: "Demo Merchant" },
    product: { title: "Monitor", condition: "NEW", bundle_contents: ["Monitor"] },
    terms: { delivery_sla_days: 7, returns_days: 30 },
    totals: { item_cents: 10000, shipping_cents: 0, tax_cents: 0, total_cents: 10000, cap_cents: 20000 },
    offer_expires_at: "2026-11-10T10:15:00Z", server_now: "2026-11-10T10:00:00Z",
    notices: { hold: "Approval places a hold.", lots_may_differ: "Lots may differ.", fallback: null },
  };
  transport.get.mockImplementation(async (path: string) => path.endsWith("/addresses") ? { data: { addresses: [] } }
    : path.endsWith("/config") ? { data: { approval_ui: "sdk_popup" } }
    : failRefresh ? { error: { error: { code: "REQUEST_FAILED", message: "Offer refresh unavailable." } } } : { data: offer });
  render(<MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><OfferCheckout buyerOrderId="offer-refresh" /></MemoryRouter>);
  fireEvent.change(await screen.findByLabelText("Name"), { target: { value: "Buyer edited" } });
  failRefresh = true;
  fireEvent.click(await screen.findByRole("button", { name: "Refresh offer state" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Offer refresh unavailable.");
  expect(screen.getByLabelText("Name")).toHaveValue("Buyer edited");
  expect(screen.getByRole("button", { name: "Retry offer" })).toBeEnabled();
  expect(transport.post).not.toHaveBeenCalled();
});

it("replaces stale checkout controls with the expired offer after a state conflict", async () => {
  let expired = false;
  const offer = {
    buyer_order_id: "offer-expired", status: "OFFERED", pool_id: "pool-one",
    merchant: {display_name: "Demo Merchant"}, product: {title: "Monitor", condition: "NEW", bundle_contents: ["Monitor"]},
    terms: {delivery_sla_days: 7, returns_days: 30},
    totals: {item_cents: 10000, shipping_cents: 0, tax_cents: 0, total_cents: 10000, cap_cents: 20000},
    offer_expires_at: "2026-11-10T10:15:00Z", server_now: "2026-11-10T10:00:00Z",
    notices: {hold: "Approval places a hold.", lots_may_differ: "Lots may differ.", fallback: null},
  };
  transport.get.mockImplementation(async (path: string) => path.endsWith("/addresses")
    ? {data: {addresses: [{id: "address-one", is_default: true, address: {name: "Demo Buyer", line1: "1 Test Street", city: "Test City", region: "NY", postal_code: "10001", country_code: "US"}}]}}
    : path.endsWith("/config") ? {data: {approval_ui: "redirect"}}
    : {data: {...offer, status: expired ? "EXPIRED" : "OFFERED"}});
  transport.post.mockImplementation(async () => {
    expired = true;
    return {error: {error: {code: "ORDER_STATE_INVALID", message: "The offer is no longer available."}}};
  });
  render(<MemoryRouter future={{v7_startTransition: true, v7_relativeSplatPath: true}}><OfferCheckout buyerOrderId="offer-expired" /></MemoryRouter>);
  await screen.findByDisplayValue("Demo Buyer");
  fireEvent.click(await screen.findByRole("button", {name: "Continue to PayPal"}));
  expect(await screen.findByRole("heading", {name: "This offer can no longer be approved."})).toBeInTheDocument();
  expect(screen.queryByRole("button", {name: "Continue to PayPal"})).toBeNull();
  expect(transport.post).toHaveBeenCalledTimes(1);
});
