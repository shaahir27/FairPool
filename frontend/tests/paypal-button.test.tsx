import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const transport = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("../src/shared/api/client", () => ({
  api: { GET: transport.get, POST: transport.post },
  API_BASE_URL: "http://localhost:8000",
}));

import { PayPalButton } from "../src/checkout/PayPalButton";
import type { ApiComponents } from "../src/shared";

type CheckoutConfig = ApiComponents["schemas"]["CheckoutConfigResponse"];
type SessionHandlers = {
  onApprove: (data: { orderId?: string | null }) => void | Promise<void>;
  onCancel: () => void | Promise<void>;
  onError: (reason: unknown) => void;
};

const CONFIG: CheckoutConfig = {
  approval_ui: "sdk_popup",
  sdk_auth: "client_id",
  client_id: "test-client-id",
  sdk_url: "https://www.sandbox.paypal.com/web-sdk/v6/core",
  components: ["paypal-payments"],
  page_type: "checkout",
  currency: "USD",
  labels: ["SANDBOX"],
};

const SHIPPING = {
  name: "Pool Buyer",
  line1: "12 Test Lane",
  line2: "",
  city: "Test City",
  region: "CA",
  postal_code: "90210",
  country_code: "US",
};

let handlers: SessionHandlers | null = null;
let started: { presentationMode: string; orderId: string } | null = null;
let createInstance: ReturnType<typeof vi.fn>;
let findEligibleMethods: ReturnType<typeof vi.fn>;

function installPaypal(eligible = true) {
  handlers = null;
  started = null;
  findEligibleMethods = vi.fn(async (_options: { currencyCode: string }) => ({
    isEligible: (method: string) => eligible && method === "paypal",
  }));
  createInstance = vi.fn(async (_options: Record<string, unknown>) => ({
    findEligibleMethods,
    createPayPalOneTimePaymentSession: (sessionHandlers: SessionHandlers) => {
      handlers = sessionHandlers;
      return {
        start: async (options: { presentationMode: "auto" }, order: Promise<{ orderId: string }>) => {
          const resolved = await order;
          started = { presentationMode: options.presentationMode, orderId: resolved.orderId };
        },
      };
    },
  }));
  (window as unknown as { paypal?: unknown }).paypal = { createInstance };
}

async function show(overrides: { config?: CheckoutConfig; ensureShipping?: () => boolean } = {}) {
  const config = overrides.config ?? CONFIG;
  const ensureShipping = overrides.ensureShipping ?? vi.fn(() => true);
  const onRefresh = vi.fn();
  const onApproved = vi.fn();
  const onFallback = vi.fn();
  const view = render(
    <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <PayPalButton
        config={config}
        buyerOrderId="order-one"
        shipping={SHIPPING}
        ensureShipping={ensureShipping}
        onRefresh={onRefresh}
        onApproved={onApproved}
        onFallback={onFallback}
      />
    </MemoryRouter>,
  );
  return { ...view, onRefresh, onApproved, onFallback, ensureShipping };
}

async function paypalElement() {
  return waitFor(() => {
    const element = document.querySelector("paypal-button");
    if (!element) throw new Error("PayPal button is not ready");
    return element;
  });
}

beforeEach(() => {
  transport.get.mockReset();
  transport.post.mockReset().mockImplementation((path: string) => {
    if (path === "/api/v1/offers/{buyer_order_id}/continue") {
      return Promise.resolve({
        data: {
          paypal_order_id: "PAYPAL-ORDER-1",
          approve_url: "https://www.sandbox.paypal.com/checkoutnow?token=PAYPAL-ORDER-1",
          approval_ui: "sdk_popup",
        },
      });
    }
    if (path === "/api/v1/offers/{buyer_order_id}/approved") {
      return Promise.resolve({
        data: { buyer_order_id: "order-one", status: "APPROVED", reason: null },
      });
    }
    if (path === "/api/v1/offers/{buyer_order_id}/cancelled") {
      return Promise.resolve({
        data: { buyer_order_id: "order-one", status: "DECLINED", reason: null },
      });
    }
    return Promise.resolve({ data: null });
  });
  delete (window as unknown as { paypal?: unknown }).paypal;
  document.querySelectorAll("script[data-paypal-sdk]").forEach((script) => script.remove());
  installPaypal();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("the PayPal SDK v6 button", () => {
  it("initialises with the public client ID and asks PayPal for eligible methods", async () => {
    await show();
    await paypalElement();

    expect(createInstance).toHaveBeenCalledWith({
      components: ["paypal-payments"],
      pageType: "checkout",
      clientId: "test-client-id",
    });
    expect(findEligibleMethods).toHaveBeenCalledWith({ currencyCode: "USD" });
  });

  it("sends the shipping address only when creating the PayPal order", async () => {
    await show();
    fireEvent.click(await paypalElement());

    await waitFor(() => expect(transport.post).toHaveBeenCalled());
    expect(transport.post.mock.calls[0]?.[0]).toBe("/api/v1/offers/{buyer_order_id}/continue");
    const body = transport.post.mock.calls[0]?.[1] as { body: Record<string, unknown> } | undefined;
    expect(body?.body).toEqual({ shipping: SHIPPING });
    expect(JSON.stringify(body?.body)).not.toMatch(/amount|cents|total|currency/i);
    await waitFor(() => expect(started).toEqual({ presentationMode: "auto", orderId: "PAYPAL-ORDER-1" }));
  });

  it.each(["OFFER_EXPIRED", "ORDER_STATE_INVALID"])("refreshes a closed offer after %s without retrying checkout", async (code) => {
    transport.post.mockResolvedValue({error: {error: {code, message: "This offer is no longer available."}}});
    const view = await show();
    fireEvent.click(await paypalElement());
    await waitFor(() => expect(view.onRefresh).toHaveBeenCalledTimes(1));
    expect(transport.post).toHaveBeenCalledTimes(1);
    expect(started).toBeNull();
  });

  it("sends only paypal_order_id on approve and reloads the offer", async () => {
    const view = await show();
    fireEvent.click(await paypalElement());
    await waitFor(() => expect(handlers).not.toBeNull());

    await act(async () => {
      await handlers?.onApprove({ orderId: "PAYPAL-ORDER-1" });
    });

    const approved = transport.post.mock.calls.find(
      ([path]) => path === "/api/v1/offers/{buyer_order_id}/approved",
    );
    expect(approved?.[1]).toEqual({
      params: { path: { buyer_order_id: "order-one" } },
      body: { paypal_order_id: "PAYPAL-ORDER-1" },
    });
    expect(JSON.stringify(approved?.[1])).not.toMatch(/amount|cents|total|currency/i);
    expect(view.onRefresh).toHaveBeenCalledTimes(1);
    expect(view.onApproved).toHaveBeenCalledTimes(1);
    expect(await screen.findByText(/Approval received/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open order for order-one" })).toHaveAttribute(
      "href",
      "/orders/order-one",
    );
  });

  it("shows a rejection reason and links to the order without refreshing", async () => {
    transport.post.mockImplementation((path: string) => {
      if (path === "/api/v1/offers/{buyer_order_id}/approved") {
        return Promise.resolve({
          data: { buyer_order_id: "order-one", status: "REJECTED", reason: "PAYEE_MISMATCH" },
        });
      }
      if (path === "/api/v1/offers/{buyer_order_id}/continue") {
        return Promise.resolve({ data: { paypal_order_id: "PAYPAL-ORDER-1" } });
      }
      return Promise.resolve({ data: null });
    });
    const view = await show();
    fireEvent.click(await paypalElement());
    await waitFor(() => expect(handlers).not.toBeNull());

    await act(async () => {
      await handlers?.onApprove({ orderId: "PAYPAL-ORDER-1" });
    });

    expect((await screen.findAllByText(/PAYEE_MISMATCH/)).length).toBeGreaterThan(0);
    expect(screen.getByRole("link", { name: "Open order for order-one" })).toHaveAttribute(
      "href",
      "/orders/order-one",
    );
    expect(view.onRefresh).not.toHaveBeenCalled();
    expect(view.onApproved).not.toHaveBeenCalled();
  });

  it("asks before a PayPal cancel declines the offer", async () => {
    const view = await show();
    fireEvent.click(await paypalElement());
    await waitFor(() => expect(handlers).not.toBeNull());

    await act(async () => {
      await handlers?.onCancel();
    });

    const dialog = await screen.findByRole("alertdialog", { name: "Cancel this PayPal approval?" });
    expect(within(dialog).getByText("Cancel now declines this offer. Keep the offer?")).toBeInTheDocument();
    expect(transport.post.mock.calls.some(([path]) => path === "/api/v1/offers/{buyer_order_id}/cancelled")).toBe(
      false,
    );

    fireEvent.click(within(dialog).getByRole("button", { name: "Keep the offer" }));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(transport.post.mock.calls.some(([path]) => path === "/api/v1/offers/{buyer_order_id}/cancelled")).toBe(
      false,
    );
    expect(view.onRefresh).not.toHaveBeenCalled();
  });

  it("declines the offer only after the confirm is accepted", async () => {
    const view = await show();
    fireEvent.click(await paypalElement());
    await waitFor(() => expect(handlers).not.toBeNull());

    await act(async () => {
      await handlers?.onCancel();
    });
    fireEvent.click(await screen.findByRole("button", { name: "Decline the offer" }));

    await waitFor(() => expect(view.onRefresh).toHaveBeenCalledTimes(1));
    const cancelled = transport.post.mock.calls.find(
      ([path]) => path === "/api/v1/offers/{buyer_order_id}/cancelled",
    );
    expect(cancelled?.[1]).toEqual({
      params: { path: { buyer_order_id: "order-one" } },
      body: {},
    });
  });

  it("falls back to the redirect flow when PayPal is not eligible", async () => {
    installPaypal(false);
    const view = await show();

    await waitFor(() => expect(view.onFallback).toHaveBeenCalledTimes(1));
    expect(view.onFallback.mock.calls[0]?.[0]).toMatch(/standard PayPal page/);
    expect(document.querySelector("paypal-button")).toBeNull();
    expect(transport.post).not.toHaveBeenCalled();
  });

  it("falls back when the SDK script cannot load", async () => {
    delete (window as unknown as { paypal?: unknown }).paypal;
    const view = await show();

    const script = await waitFor(() => {
      const element = document.querySelector<HTMLScriptElement>("script[data-paypal-sdk]");
      if (!element) throw new Error("SDK script was not injected");
      return element;
    });
    act(() => {
      script.dispatchEvent(new Event("error"));
    });

    await waitFor(() => expect(view.onFallback).toHaveBeenCalledTimes(1));
    expect(view.onFallback.mock.calls[0]?.[0]).toMatch(/could not load/);
    expect(document.querySelector("paypal-button")).toBeNull();
  });

  it("uses the server's client token when that mode is configured", async () => {
    transport.get.mockResolvedValue({ data: { client_token: "client-token-one", expires_in: 900 } });
    await show({ config: { ...CONFIG, sdk_auth: "client_token" } });
    await paypalElement();

    expect(transport.get).toHaveBeenCalledWith("/api/v1/checkout/client-token");
    expect(createInstance).toHaveBeenCalledWith({
      components: ["paypal-payments"],
      pageType: "checkout",
      clientToken: "client-token-one",
    });
  });

  it("falls back when the SDK never finishes initialising", async () => {
    delete (window as unknown as { paypal?: unknown }).paypal;
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const view = await show();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(8_000);
    });

    expect(view.onFallback).toHaveBeenCalledTimes(1);
    expect(view.onFallback.mock.calls[0]?.[0]).toMatch(/standard PayPal page/);
    expect(document.querySelector("paypal-button")).toBeNull();
    vi.useRealTimers();
  });

  it("does not create an order until the shipping address is complete", async () => {
    const view = await show({ ensureShipping: vi.fn(() => false) });
    fireEvent.click(await paypalElement());

    expect(view.ensureShipping).toHaveBeenCalled();
    expect(transport.post).not.toHaveBeenCalled();
  });
});
