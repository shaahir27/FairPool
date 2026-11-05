import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const transport = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  remove: vi.fn(),
}));
vi.mock("../src/shared/api/client", () => ({
  api: {
    GET: transport.get,
    POST: transport.post,
    PUT: transport.put,
    DELETE: transport.remove,
  },
  API_BASE_URL: "http://localhost:8000",
}));

import { DemandPage } from "../src/merchant/demand/DemandPage";
import { ProfilePage } from "../src/merchant/profile/ProfilePage";
import { envelope, honestyKinds, productName, shortId } from "../src/shared";

function lot(overrides: Record<string, unknown> = {}) {
  return {
    lot_id: "lot-one",
    pool_id: "pool-one",
    zone_id: "US-EAST",
    seats: 12,
    min_seats: 6,
    status: "BIDDING",
    bid_close_at: "2026-11-05T18:00:00Z",
    product_key: "monitor-27-4k",
    variant: "black",
    condition: "NEW",
    delivery_sla_days: 5,
    min_return_days: 30,
    ...overrides,
  };
}

const structured = {
  v: 1,
  product_key: "monitor-27-4k",
  condition: "NEW",
  bundle_contents: ["monitor", "stand"],
  capacity: 3,
  target_quantity: 3,
  moq: 2,
  tiers: [
    { min_qty: 1, item_price_cents: 50000 },
    { min_qty: 3, item_price_cents: 47000 },
  ],
  shipping_cents_by_zone: { "US-EAST": 0 },
  tax: { mode: "INCLUDED" },
  delivery: { sla_days: 5 },
  returns: { days: 30 },
  valid_until: "2026-11-30",
  evidence: { note: "Units reserved in warehouse A" },
};

function showDemand() {
  return render(
    <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }} initialEntries={["/merchant/demand"]}>
      <Routes>
        <Route path="/merchant/demand" element={<DemandPage />} />
        <Route path="/merchant/bids" element={<div>active bids destination</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

function showProfile() {
  return render(
    <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }} initialEntries={["/merchant/profile"]}>
      <Routes>
        <Route path="/merchant/profile" element={<ProfilePage />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  transport.get.mockReset();
  transport.post.mockReset();
  transport.put.mockReset();
  transport.remove.mockReset();
});

describe("Demand Board", () => {
  it("moves keyboard focus to the bid composer when it opens", async () => {
    transport.get.mockResolvedValue({ data: [lot()] });
    showDemand();

    fireEvent.click(await screen.findByRole("button", { name: "Prepare a bid" }));

    expect(screen.getByRole("heading", { name: "Prepare a sealed bid" })).toHaveFocus();
  });

  it("filters the loaded lots without a request per keystroke", async () => {
    transport.get.mockResolvedValue({
      data: [lot(), lot({ lot_id: "lot-two", product_key: "ceramic-kettle", variant: "cream" })],
    });
    showDemand();

    expect(await screen.findByRole("heading", { level: 1, name: "Demand Board" })).toBeInTheDocument();
    await screen.findByText("monitor-27-4k");
    expect(screen.getByText("ceramic-kettle")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Search open lots"), { target: { value: "kettle" } });

    expect(screen.queryByText("monitor-27-4k")).not.toBeInTheDocument();
    expect(screen.getByText("ceramic-kettle")).toBeInTheDocument();
    expect(screen.getByRole("status", { name: "Lot search results" })).toHaveTextContent("1 of 2 lots");
    expect(transport.get).toHaveBeenCalledTimes(1);
  });

  it("offers the manual form when the quote parser is switched off", async () => {
    transport.get.mockResolvedValue({ data: [lot()] });
    transport.post.mockResolvedValue({
      error: {
        error: {
          code: "FEATURE_DISABLED",
          message: "Quote parsing is not enabled in this environment.",
        },
      },
    });
    showDemand();

    fireEvent.click(await screen.findByRole("button", { name: "Prepare a bid" }));
    fireEvent.change(screen.getByLabelText("Paste your quote"), {
      target: { value: "27-inch monitors, $500 each, minimum 2." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Parse quote" }));

    expect(await screen.findByText(/Quote parsing is unavailable/)).toBeInTheDocument();
    expect(screen.getByText("FEATURE_DISABLED")).toBeInTheDocument();
    expect(screen.getByLabelText("Bid fields (JSON)")).toBeInTheDocument();
  });

  it("saves nothing until the bid is confirmed, then shows the receipt hash", async () => {
    transport.get.mockResolvedValue({ data: [lot()] });
    transport.post.mockImplementation((path: string) => {
      if (path === "/api/v1/merchant/lots/{lot_id}/quote") {
        return Promise.resolve({
          data: {
            bid_id: "bid-one",
            revision: 1,
            status: "PROPOSED",
            proposed_fields: structured,
            ambiguities: [{ field: "valid_until", question: "How long should this offer stay valid?" }],
          },
        });
      }
      if (path === "/api/v1/merchant/bids/{bid_id}/confirm") {
        return Promise.resolve({
          data: { bid_id: "bid-one", revision: 1, status: "CONFIRMED" },
        });
      }
      return Promise.resolve({ error: { error: { code: "NOT_FOUND" } } });
    });
    transport.put.mockResolvedValue({
      data: {
        bid_id: "bid-one",
        revision: 1,
        status: "PROPOSED",
        receipt: { hash: "a".repeat(64), signature: "signature-value" },
      },
    });
    showDemand();

    fireEvent.click(await screen.findByRole("button", { name: "Prepare a bid" }));
    fireEvent.change(screen.getByLabelText("Paste your quote"), {
      target: { value: "27-inch monitors, $500 each, minimum 2." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Parse quote" }));

    expect(await screen.findByText("How long should this offer stay valid?")).toBeInTheDocument();
    const editor = screen.getByLabelText("Bid fields (JSON)");
    expect(editor).toHaveValue(JSON.stringify(structured, null, 2));

    fireEvent.click(screen.getByRole("button", { name: "Review bid" }));
    const review = await screen.findByRole("region", { name: "Confirm this bid" });
    expect(within(review).getByText("$470.00")).toBeInTheDocument();
    expect(within(review).getByText(/Nothing is saved until/)).toBeInTheDocument();
    expect(transport.put).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Save and confirm bid" }));

    expect(await screen.findByText("Bid confirmed")).toBeInTheDocument();
    expect(screen.getByText("a".repeat(64))).toBeInTheDocument();

    const putCall = transport.put.mock.calls[0];
    expect(putCall?.[0]).toBe("/api/v1/merchant/lots/{lot_id}/bid");
    const putInit = putCall?.[1] as {
      params: { path: { lot_id: string } };
      headers: Record<string, string>;
      body: { structured: { product_key: string } };
    };
    expect(putInit.params.path).toEqual({ lot_id: "lot-one" });
    expect(putInit.headers["Idempotency-Key"]).toEqual(expect.any(String));
    expect(putInit.body.structured.product_key).toBe("monitor-27-4k");

    const confirmCall = transport.post.mock.calls.find(
      ([path]) => path === "/api/v1/merchant/bids/{bid_id}/confirm",
    );
    expect(confirmCall).toBeDefined();
    expect((confirmCall?.[1] as { body: { revision: number } }).body).toEqual({ revision: 1 });
  });
});

describe("Merchant profile", () => {
  it("prefills the account name, records the three attestations and shows the server's status", async () => {
    transport.get.mockResolvedValue({
      data: { display_name: "Demo Merchant Alpha", role: "merchant", paypal_linked: false },
    });
    transport.post.mockResolvedValue({
      data: {
        merchant_id: "merchant-one",
        display_name: "Demo Merchant Alpha",
        onboarding_status: "DEMO",
        attestations: {
          inventory_reserved: { at: "2026-11-04T09:00:00Z", accepted: true },
          map_compliance: { at: "2026-11-04T09:00:00Z", accepted: true },
          delivery_terms_accurate: { at: "2026-11-04T09:00:00Z", accepted: true },
        },
      },
    });
    showProfile();

    const name = await screen.findByLabelText("Display name");
    await waitFor(() => expect(name).toHaveValue("Demo Merchant Alpha"));

    fireEvent.change(screen.getByLabelText("Payee email (optional)"), {
      target: { value: "seller@example.test" },
    });
    for (const label of [
      /Inventory is reserved/,
      /minimum advertised price/,
      /Delivery and return terms/,
    ]) {
      fireEvent.click(screen.getByLabelText(label));
    }
    fireEvent.click(screen.getByRole("button", { name: "Save profile" }));

    expect(await screen.findByText("DEMO")).toBeInTheDocument();
    expect(screen.getByText("FALLBACK: single stand-in seller")).toBeInTheDocument();

    const [, init] = transport.post.mock.calls[0] ?? [];
    expect(transport.post.mock.calls[0]?.[0]).toBe("/api/v1/merchant/profile");
    expect(init?.body).toEqual({
      display_name: "Demo Merchant Alpha",
      payee_email: "seller@example.test",
      attestations: {
        inventory_reserved: { accepted: true },
        map_compliance: { accepted: true },
        delivery_terms_accurate: { accepted: true },
      },
    });
  });

  it("sends only the fields the merchant edited, so blank fields keep the stored row", async () => {
    transport.get.mockResolvedValue({
      data: { display_name: "Demo Merchant Alpha", role: "merchant", paypal_linked: false },
    });
    transport.post.mockResolvedValue({
      data: {
        merchant_id: "merchant-one",
        display_name: "Demo Merchant Alpha",
        onboarding_status: "DEMO",
        attestations: {},
      },
    });
    showProfile();

    const name = await screen.findByLabelText("Display name");
    await waitFor(() => expect(name).toHaveValue("Demo Merchant Alpha"));
    expect(
      screen.getByText(/Leave a payee field blank to keep the value already saved/),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Save profile" }));

    await waitFor(() => expect(transport.post).toHaveBeenCalledTimes(1));
    const body = (transport.post.mock.calls[0]?.[1] as { body: unknown }).body;
    expect(body).toEqual({ display_name: "Demo Merchant Alpha" });
  });
});

describe("shared display helpers", () => {
  it("has one copy for every workspace", () => {
    expect(envelope({ error: { code: "RATE_LIMITED", message: "Slow down." } })).toEqual({
      code: "RATE_LIMITED",
      message: "Slow down.",
    });
    expect(envelope(undefined)).toEqual({
      code: "REQUEST_FAILED",
      message: "The request could not be completed.",
    });
    expect(honestyKinds(["SANDBOX", "FALLBACK: one seller", "OTHER"])).toEqual([
      "sandbox",
      "fallback",
    ]);
    expect(productName("monitor-27-4k")).toBe("Monitor 27 4k");
    expect(productName(null)).toBe("Lot");
    expect(shortId("1234567890123")).toBe("12345678…");
  });
});
