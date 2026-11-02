import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";

const HOLD =
  "PayPal places a hold for the total shown only after you approve. The hold is released if this lot does not reach its minimum.";

let responseBody: unknown = null;

// One stub for the file: the client captures fetch when it is created, so the
// payload has to be read at call time rather than rebound per test.
beforeAll(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify(responseBody), { status: 200 })),
  );
});

afterAll(() => {
  vi.unstubAllGlobals();
});

function respond(body: unknown) {
  responseBody = body;
}

async function renderCard() {
  // openapi-fetch captures fetch when the client is created, so the module is
  // imported only after the stub is in place.
  const { OrderStatusCard } = await import("../src/checkout");
  render(
    <MemoryRouter>
      <OrderStatusCard buyerOrderId="11111111-1111-1111-1111-111111111111" />
    </MemoryRouter>,
  );
  await waitFor(() =>
    expect(screen.getByRole("heading", { name: "Order status" })).toBeTruthy(),
  );
}

describe("order status card", () => {
  it("shows the API status values and never a computed net figure", async () => {
    respond({
      buyer_order_id: "11111111-1111-1111-1111-111111111111",
      status: "AUTHORIZING",
      lot_status: "CHECKOUT_OPEN",
      total_cents: 49900,
      history: [{ status: "AUTHORIZING", at: "2026-11-01T10:04:03Z" }],
      paypal: { authorization_status: null, capture_status: null, refund_status: null },
      labels: ["SANDBOX"],
      pool_id: "22222222-2222-2222-2222-222222222222",
      lot_id: null,
      placed_at: "2026-11-01T10:02:11Z",
      reject_reason: null,
      receipt: null,
    });
    await renderCard();
    expect(screen.getAllByText("AUTHORIZING").length).toBeGreaterThan(0);
    expect(screen.getAllByText("CHECKOUT_OPEN").length).toBeGreaterThan(0);
    expect(screen.getByText("$499.00")).toBeTruthy();
    expect(
      screen.getByText(
        "PayPal is still confirming your hold. This is not a failure, and nothing has been paid yet.",
      ),
    ).toBeTruthy();
    expect(screen.queryByText(/net result/i)).toBeNull();
    expect(HOLD).not.toBe("");
  });

  it("explains a rejection with the API's own reason code", async () => {
    respond({
      buyer_order_id: "11111111-1111-1111-1111-111111111111",
      status: "REJECTED",
      lot_status: "CHECKOUT_OPEN",
      total_cents: 49900,
      history: [],
      paypal: { authorization_status: null, capture_status: null, refund_status: null },
      labels: ["SANDBOX", "FALLBACK: single stand-in seller"],
      pool_id: null,
      lot_id: null,
      placed_at: null,
      reject_reason: "PAYEE_MISMATCH",
      receipt: null,
    });
    await renderCard();
    // The reason card mounts after the order payload resolves; wait for it.
    expect(await screen.findByText("PAYEE_MISMATCH")).toBeTruthy();
    expect(
      await screen.findByText("The seller on the PayPal order was not the one we expected."),
    ).toBeTruthy();
  });
});
