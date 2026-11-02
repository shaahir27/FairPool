import { act, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const transport = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("../src/shared/api/client", () => ({
  api: { GET: transport.get, POST: transport.post },
  API_BASE_URL: "http://localhost:8000",
}));

import { OfferCheckout, OrderStatusCard } from "../src/checkout";
import { LoginPage, RegisterPage } from "../src/buyer/pages";
import { useCountdown } from "../src/shared";

const offer = {
  buyer_order_id: "order-one", status: "OFFERED",
  merchant: { display_name: "Demo Merchant Alpha" },
  product: { title: "27-inch 4K monitor", variant: "Black", condition: "NEW", bundle_contents: ["Monitor", "Stand", "Cable"] },
  terms: { delivery_sla_days: 7, returns_days: 30 },
  totals: { item_cents: 48000, shipping_cents: 1000, tax_cents: 900, total_cents: 49900, cap_cents: 60000 },
  offer_expires_at: "2026-11-02T10:15:00Z", offer_started_at: "2026-11-02T10:00:00Z", server_now: "2026-11-02T10:02:00Z",
  pool_id: "pool-one", pool_title: "Monitor pool",
  notices: { hold: "A hold is placed only after approval.", lots_may_differ: "Separate lots may have different prices.", fallback: null },
};

function show(component: React.ReactNode) {
  return render(<MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>{component}</MemoryRouter>);
}

beforeEach(() => {
  transport.get.mockReset().mockResolvedValue({ data: offer });
  transport.post.mockReset();
});
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

describe("checkout actions", () => {
  it("keeps a server-valid offer payable when the device clock is ahead", async () => {
    vi.spyOn(Date, "now").mockReturnValue(Date.parse("2026-11-03T10:00:00Z"));
    show(<OfferCheckout buyerOrderId="order-one" />);
    expect(await screen.findByRole("button", { name: /Continue to PayPal/ })).toBeEnabled();
    expect(screen.getByText("13:00")).toBeInTheDocument();
    vi.restoreAllMocks();
  });

  it("requires a complete shipping address before continuing", async () => {
    show(<OfferCheckout buyerOrderId="order-one" />);
    fireEvent.click(await screen.findByRole("button", { name: /Continue to PayPal/ }));
    expect(transport.post).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Name")).toBeInvalid();
  });

  it("keeps the offer visible when decline fails and allows a retry", async () => {
    transport.post.mockResolvedValue({ error: { error: { code: "ORDER_STATE_INVALID", message: "Please refresh the offer." } } });
    show(<OfferCheckout buyerOrderId="order-one" />);
    fireEvent.click(await screen.findByRole("button", { name: /^Decline/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("ORDER_STATE_INVALID");
    expect(screen.getByRole("heading", { name: "27-inch 4K monitor" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Decline/ })).toBeEnabled();
  });

  it("replaces a declined offer with a terminal state", async () => {
    transport.get.mockResolvedValue({ data: { ...offer, status: "DECLINED" } });
    show(<OfferCheckout buyerOrderId="order-one" />);
    expect(await screen.findByRole("heading", { name: /declined/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Continue to PayPal/ })).not.toBeInTheDocument();
  });
});

it("counts down across re-renders using the same server clock sample", () => {
  vi.useFakeTimers({ toFake: ["Date", "setInterval", "clearInterval", "performance"] });
  vi.setSystemTime(new Date("2026-11-03T10:00:00Z"));
  const { result, rerender } = renderHook(() => useCountdown("2026-11-02T10:02:03Z", "2026-11-02T10:02:00Z"));
  act(() => vi.advanceTimersByTime(2000));
  rerender();
  expect(result.current.remainingMs).toBe(1000);
  act(() => vi.advanceTimersByTime(1000));
  expect(result.current.expired).toBe(true);
});

it("loads the order item from its existing offer disclosure endpoint", async () => {
  transport.get.mockImplementation(async (path: string) => ({ data: path.includes("offers") ? offer : {
    buyer_order_id: "order-one", status: "AUTHORIZED", lot_status: "CHECKOUT_OPEN", total_cents: 49900,
    history: [], paypal: {}, labels: ["SANDBOX"], receipt: null,
  } }));
  show(<OrderStatusCard buyerOrderId="order-one" />);
  expect(await screen.findByText("27-inch 4K monitor")).toBeInTheDocument();
  expect(screen.getAllByText("Demo Merchant Alpha").length).toBeGreaterThan(0);
  expect(screen.getByText("Delivery within 7 days")).toBeInTheDocument();
});

it("keeps withdrawal visibly unavailable while its route is unbuilt", async () => {
  transport.get.mockResolvedValue({ data: {
    buyer_order_id: "order-one", status: "AUTHORIZED", lot_status: "CHECKOUT_OPEN", total_cents: 49900,
    history: [], paypal: { authorization_status: "CREATED" }, labels: ["SANDBOX"], receipt: null,
  } });
  show(<OrderStatusCard buyerOrderId="order-one" />);
  fireEvent.click(await screen.findByRole("button", { name: /Payment details/ }));
  const button = await screen.findByRole("button", { name: "Withdraw before payment" });

  // POST /orders/{id}/withdraw is a later task: an active button would 500 on the
  // stub route, so the action is disabled and says so instead of failing silently.
  expect(button).toBeDisabled();
  fireEvent.click(button);
  expect(transport.post).not.toHaveBeenCalled();
  expect(screen.getAllByText("AUTHORIZED").length).toBeGreaterThan(0);
  expect(screen.queryByText("Your hold was released.")).not.toBeInTheDocument();
});

describe("authentication recovery", () => {
  it.each([
    ["Sign in", <LoginPage />], ["Create account", <RegisterPage />],
  ])("%s recovers from a disconnected request", async (label, component) => {
    transport.post.mockRejectedValue(new TypeError("network unavailable"));
    show(component);
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "buyer@example.test" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "test-password" } });
    if (label === "Create account") fireEvent.change(screen.getByLabelText("Display name"), { target: { value: "Buyer" } });
    fireEvent.submit(screen.getByRole("button", { name: label }).closest("form")!);
    expect(await screen.findByRole("alert")).toHaveTextContent(/connection|try again/i);
    expect(screen.getByRole("button", { name: label })).toBeEnabled();
  });
});

it("opens the private receipt as a closable dialog", async () => {
  // jsdom does not implement the native dialog's top-layer methods.
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
  transport.get.mockResolvedValue({ data: {
    buyer_order_id: "order-one", status: "AUTHORIZING", lot_status: "CHECKOUT_OPEN", total_cents: 49900,
    history: [], paypal: {}, labels: ["SANDBOX"], receipt: {
      payload: { commitment: "commitment-one", entry_id: "entry-one", pool_id: "pool-one", received_at: "2026-11-02T10:00:00Z", v: 1 },
      salt_hex: "salt-one", request_hash: "hash-one", signature: "signature-one",
    },
  } });
  show(<OrderStatusCard buyerOrderId="order-one" />);
  fireEvent.click(await screen.findByRole("button", { name: /View entry receipt/ }));
  const dialog = await screen.findByRole("dialog", { name: "Entry receipt" });
  expect(dialog).toHaveTextContent("commitment-one");
  fireEvent.click(screen.getByRole("button", { name: "Close receipt" }));
  await waitFor(() => expect(dialog).not.toHaveAttribute("open"));
});

it("keeps payment diagnostics behind an explicit disclosure", async () => {
  transport.get.mockResolvedValue({ data: {
    buyer_order_id: "order-one", status: "AUTHORIZING", lot_status: "CHECKOUT_OPEN", total_cents: 49900,
    history: [], paypal: { authorization_status: "CREATED", capture_status: null, refund_status: null }, labels: ["SANDBOX"], receipt: null,
  } });
  show(<OrderStatusCard buyerOrderId="order-one" />);
  const toggle = await screen.findByRole("button", { name: /Payment details/ });
  expect(toggle).toHaveAttribute("aria-expanded", "false");
  expect(screen.queryByText("CREATED")).not.toBeInTheDocument();
  fireEvent.click(toggle);
  expect(await screen.findByText("CREATED")).toBeInTheDocument();
  expect(toggle).toHaveAttribute("aria-expanded", "true");
});

it("keeps the existing order readable while refreshing", async () => {
  const data = { buyer_order_id: "order-one", status: "AUTHORIZING", lot_status: "CHECKOUT_OPEN", total_cents: 49900, history: [], paypal: {}, labels: [], receipt: null };
  let refresh = false;
  transport.get.mockImplementation(async (path: string) => {
    if (path.includes("/orders/")) {
      if (refresh) return new Promise(() => {});
      return { data };
    }
    return { data: null };
  });
  show(<OrderStatusCard buyerOrderId="order-one" />);
  await screen.findByRole("heading", { level: 1, name: "Order status" });
  refresh = true;
  fireEvent.click(screen.getByRole("button", { name: "Refresh status" }));
  expect(screen.getByRole("heading", { level: 1, name: "Order status" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Refreshing/ })).toBeDisabled();
});
