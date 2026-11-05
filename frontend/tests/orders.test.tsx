import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
const transport = vi.hoisted(() => ({get: vi.fn(), post: vi.fn()}));
vi.mock("../src/shared/api/client", () => ({api: {GET: transport.get, POST: transport.post}, API_BASE_URL: "http://localhost:8000"}));
import { OrdersPage } from "../src/buyer/orders/OrdersPage";
import { resetBuyerPrefetch } from "../src/buyer/prefetch";
const paid = {buyer_order_id: "order-paid", lot_id: "lot-one", pool_id: "pool-one", pool_title: "Workstation pool", status: "CAPTURED", total_cents: 49900, receipt: {commitment: "c".repeat(64)}, product: {title: "27-inch monitor", variant: "Black", condition: "NEW", bundle_contents: ["Monitor", "Stand"]}, merchant: {display_name: "Demo Merchant"}, terms: {delivery_sla_days: 5, returns_days: 30}, capture_id: "CAP-LIST-1", placed_at: "2026-11-01T12:00:00Z", labels: ["SANDBOX"]};
const progress = {...paid, buyer_order_id: "order-progress", status: "AUTHORIZING", product: {...paid.product, title: "Desk lamp"}, capture_id: null, receipt: null, total_cents: 12345};
function show() {return render(<MemoryRouter future={{v7_startTransition: true, v7_relativeSplatPath: true}}><OrdersPage /></MemoryRouter>);}
function orders(items: unknown[]) {transport.get.mockResolvedValue({data: {items}});}
beforeEach(() => {resetBuyerPrefetch(); transport.get.mockReset(); transport.post.mockReset(); vi.restoreAllMocks();});

it("shows a single named purchase feed with merchant, terms, amount and payment status", async () => {
  orders([paid, progress]); show();
  const feed = await screen.findByRole("list", {name: "Your orders"});
  expect(within(feed).getAllByRole("listitem")).toHaveLength(2);
  expect(screen.getByRole("heading", {name: "27-inch monitor"})).toBeInTheDocument();
  expect(screen.getAllByText("Demo Merchant")).toHaveLength(2);
  expect(screen.getByText("$499.00")).toBeInTheDocument();
  expect(screen.getAllByText(/Delivery within 5 days/)).toHaveLength(2);
  expect(screen.getByText("Payment completed")).toBeInTheDocument();
  expect(screen.getByText("Confirming the hold")).toBeInTheDocument();
  expect(screen.queryByRole("heading", {name: "Paid"})).toBeNull();
  expect(screen.queryByRole("heading", {name: "In progress"})).toBeNull();
});
it("uses the list's capture reference without a detail request per purchase", async () => {
  orders([paid, progress]); show(); await screen.findByText("27-inch monitor");
  expect(await screen.findByText("CAP-LIST-1")).toBeInTheDocument();
  expect(transport.get).toHaveBeenCalledTimes(1);
});
it("keeps internal states and IDs under references instead of making them the purchase title", async () => {
  orders([paid]); show();
  const reference = await screen.findByText("order-paid");
  expect(reference.closest("details")?.open).toBe(false);
  expect(screen.getByText("CAPTURED").closest("details")?.open).toBe(false);
  expect(screen.getByRole("link", {name: "Open order and receipt for order-paid"})).toHaveTextContent("View order");
});
it("filters payment outcomes in place with no extra request", async () => {
  orders([paid, progress]); show(); await screen.findByText("Desk lamp");
  fireEvent.change(screen.getByLabelText("Payment status"), {target: {value: "paid"}});
  expect(screen.queryByRole("heading", {name: "Desk lamp"})).toBeNull();
  expect(screen.getByRole("heading", {name: "27-inch monitor"})).toBeInTheDocument();
  expect(transport.get).toHaveBeenCalledTimes(1);
});
it("finds a purchase by product or merchant and recovers from an empty filter", async () => {
  orders([paid, progress]); show(); await screen.findByText("Desk lamp");
  fireEvent.change(screen.getByLabelText("Search your orders"), {target: {value: "lamp"}});
  expect(screen.queryByRole("heading", {name: "27-inch monitor"})).toBeNull();
  fireEvent.change(screen.getByLabelText("Payment status"), {target: {value: "released"}});
  expect(screen.getByRole("heading", {name: "No matching orders"})).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", {name: "Clear filters"}));
  expect(screen.getByRole("heading", {name: "27-inch monitor"})).toBeInTheDocument();
});
it("does not treat a capture reference as payment success", async () => {
  orders([{...paid, status: "OFFERED"}]); show();
  expect(await screen.findByText("Offer sent")).toBeInTheDocument();
  expect(screen.queryByText("Payment completed")).toBeNull();
});
it("shows refund and hold-release states distinctly", async () => {
  orders([{...paid, buyer_order_id: "refunded", status: "REFUNDED"}, {...progress, status: "VOIDED"}]); show();
  expect(await screen.findByText("Refunded")).toBeInTheDocument();
  expect(screen.getByText("Hold released")).toBeInTheDocument();
});
it("keeps capture reads compatible with an older API that omits the list field", async () => {
  const legacy: Record<string, unknown> = {...paid}; delete legacy.capture_id;
  transport.get.mockImplementation(async (path: string) => path === "/api/v1/me/orders" ? {data: {items: [legacy]}} : {data: {paypal: {capture_id: "CAP-LEGACY"}}});
  show(); expect(await screen.findByText("CAP-LEGACY")).toBeInTheDocument();
  expect(transport.get).toHaveBeenCalledTimes(2);
});
it("copies the payment reference only when the buyer asks", async () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", {value: {writeText}, configurable: true});
  orders([paid]); show(); await screen.findByText("27-inch monitor");
  expect(writeText).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText("Order details and references"));
  fireEvent.click(screen.getByRole("button", {name: "Copy PayPal capture reference for order-paid"}));
  expect(await screen.findByText("PayPal payment reference copied.")).toBeInTheDocument();
  expect(writeText).toHaveBeenCalledWith("CAP-LIST-1");
});
it("distinguishes a failed legacy capture read from no capture", async () => {
  const legacy: Record<string, unknown> = {...paid}; delete legacy.capture_id;
  transport.get.mockImplementation(async (path: string) => path === "/api/v1/me/orders" ? {data: {items: [legacy]}} : {error: {error: {code: "REQUEST_FAILED"}}});
  show(); expect(await screen.findByText("The PayPal capture reference could not be loaded.")).toBeInTheDocument();
  expect(screen.queryByText("No PayPal capture yet.")).toBeNull();
});
it("does not flash an empty history before the list arrives", async () => {
  let finish!: (value: unknown) => void; transport.get.mockReturnValue(new Promise((resolve) => {finish = resolve;}));
  show(); expect(screen.getByRole("status", {name: "Loading your orders"})).toBeInTheDocument();
  expect(screen.queryByText("No orders yet")).toBeNull();
  await act(async () => {finish({data: {items: [paid]}});});
  expect(await screen.findByRole("heading", {name: "27-inch monitor"})).toBeInTheDocument();
});
it("offers a retry after a history error and a useful first-use empty state", async () => {
  transport.get.mockResolvedValueOnce({error: {error: {code: "REQUEST_FAILED", message: "Offline."}}}).mockResolvedValueOnce({data: {items: []}});
  show(); expect(await screen.findByText(/Offline/)).toBeInTheDocument();
  expect(screen.queryByText("No orders yet")).toBeNull();
  fireEvent.click(screen.getByRole("button", {name: "Try again"}));
  expect(await screen.findByRole("heading", {name: "No orders yet"})).toBeInTheDocument();
});
