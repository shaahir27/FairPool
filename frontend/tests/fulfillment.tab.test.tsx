import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const transport = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("../src/shared/api/client", () => ({
  api: { GET: transport.get, POST: transport.post },
  API_BASE_URL: "http://localhost:8000",
}));

import { FulfillmentPage } from "../src/merchant-fulfillment";

type GetInit = { params?: { path?: { lot_id?: string } } };

const bids = {
  items: [
    {
      bid_id: "bid-funded",
      lot_id: "lot-funded",
      status: "AWARDED",
      current_revision: 2,
      structured: { product_key: "monitor-27-4k" },
      flags: [],
      reject_reason: null,
    },
    {
      bid_id: "bid-open",
      lot_id: "lot-open",
      status: "AWARDED",
      current_revision: 1,
      structured: { product_key: "ceramic-kettle" },
      flags: [],
      reject_reason: null,
    },
    {
      bid_id: "bid-lost",
      lot_id: "lot-lost",
      status: "LOST",
      current_revision: 1,
      structured: { product_key: "desk-lamp" },
      flags: [],
      reject_reason: null,
    },
  ],
};

const rows = [
  {
    buyer_order_id: "bo-one",
    name: "Ada Lovelace",
    line1: "12 Analytical Way",
    line2: null,
    city: "New York",
    region: "NY",
    postal_code: "10001",
    country_code: "US",
    item_cents: 42000,
    shipping_cents: 900,
    tax_cents: 3500,
    total_cents: 46400,
    paypal_capture_id: "CAP-ONE",
  },
  {
    buyer_order_id: "bo-two",
    name: "Grace Hopper",
    line1: "1 Compiler Court",
    line2: "Apt 2",
    city: "Arlington",
    region: "VA",
    postal_code: "22201",
    country_code: "US",
    item_cents: 30000,
    shipping_cents: 500,
    tax_cents: 2100,
    total_cents: 32600,
    paypal_capture_id: "CAP-TWO",
  },
];

const manifest = {
  lot_id: "lot-funded",
  currency: "USD",
  funded: true,
  expected_captured_total_cents: 79000,
  items: [
    {
      paypal_order_id: "PAYPAL-ORDER-1",
      paypal_capture_id: "CAP-ONE",
      amount_cents: 46400,
      captured_at: "2026-11-02T10:00:00Z",
    },
  ],
  how_to_verify:
    "In your AI client connected to the PayPal MCP server, look up each order ID with a read-only get-order tool and confirm the capture amounts add up to expected_captured_total_cents.",
};

const verification = {
  lot_id: "lot-funded",
  checked_at: "2026-11-02T12:00:00Z",
  matched: 1,
  total: 2,
  all_match: false,
  expected_captured_total_cents: 79000,
  paypal_captured_total_cents: 46400,
  items: [
    {
      paypal_order_id: "PAYPAL-ORDER-1",
      paypal_capture_id: "CAP-ONE",
      expected_amount_cents: 46400,
      paypal_capture_status: "COMPLETED",
      paypal_amount_cents: 46400,
      match: true,
    },
    {
      paypal_order_id: "PAYPAL-ORDER-2",
      paypal_capture_id: "CAP-TWO",
      expected_amount_cents: 32600,
      paypal_capture_status: "PENDING",
      paypal_amount_cents: 32600,
      match: false,
    },
  ],
};

const notFunded = {
  error: { error: { code: "LOT_NOT_FUNDED", message: "This lot is not funded yet." } },
  response: { status: 409 },
};

function progress(lotId: string, status: string) {
  return {
    lot_id: lotId,
    status,
    seats: 3,
    moq: 3,
    holds_placed: 3,
    captures_completed: 3,
    refills_offered: 0,
    counts: { CAPTURED: 3 },
    fund_deadline_at: null,
    labels: ["SANDBOX"],
  };
}

function server(options: { fulfillment?: unknown; lotStatus?: string } = {}) {
  transport.get.mockImplementation((path: string, init?: GetInit) => {
    const lotId = init?.params?.path?.lot_id ?? "";
    if (path === "/api/v1/merchant/bids") return Promise.resolve({ data: bids });
    if (path === "/api/v1/merchant/lots/{lot_id}/progress") {
      const status =
        options.lotStatus ?? (lotId === "lot-funded" ? "FUNDED" : "FUNDING");
      return Promise.resolve({ data: progress(lotId, status) });
    }
    if (path === "/api/v1/merchant/lots/{lot_id}/fulfillment") {
      return Promise.resolve(options.fulfillment ?? { data: rows });
    }
    if (path === "/api/v1/merchant/lots/{lot_id}/verification-manifest") {
      return Promise.resolve({ data: manifest });
    }
    if (path === "/api/v1/merchant/lots/{lot_id}/verification") {
      return Promise.resolve({ data: verification });
    }
    return Promise.resolve({ data: [] });
  });
}

function show() {
  return render(
    <MemoryRouter
      future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      initialEntries={["/merchant/fulfillment"]}
    >
      <FulfillmentPage />
    </MemoryRouter>,
  );
}

let downloads: string[] = [];

beforeEach(() => {
  downloads = [];
  transport.get.mockReset();
  transport.post.mockReset();
  server();
  Object.defineProperty(URL, "createObjectURL", {
    value: () => "blob:fairpool",
    configurable: true,
  });
  Object.defineProperty(URL, "revokeObjectURL", { value: () => {}, configurable: true });
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
    this: HTMLAnchorElement,
  ) {
    downloads.push(this.download);
  });
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("Fulfillment tab", () => {
  it("picks from the awarded lots, opens the funded one and shows its captured rows", async () => {
    show();

    const picker = await screen.findByRole("combobox", { name: "Awarded lot" });
    const labels = within(picker)
      .getAllByRole("option")
      .map((option) => option.textContent ?? "");
    expect(labels).toHaveLength(2);
    expect(labels.join(" | ")).toContain("Monitor 27 4k");
    expect(labels.join(" | ")).toContain("FUNDED");
    expect(labels.join(" | ")).toContain("FUNDING");
    // A lost bid is not an awarded lot, so it is never offered.
    expect(labels.join(" | ")).not.toContain("Desk lamp");

    expect(await screen.findByRole("heading", { name: "Captured orders" })).toBeInTheDocument();
    expect(screen.getByText("Ada Lovelace")).toBeInTheDocument();
    expect(screen.getByText("12 Analytical Way")).toBeInTheDocument();
    expect(screen.getByText("$464.00")).toBeInTheDocument();
    expect(screen.getByText("CAP-ONE")).toBeInTheDocument();
    expect(screen.getByText("SANDBOX")).toBeInTheDocument();
  });

  it("downloads the shipping CSV the API renders, asking for text/csv", async () => {
    const text = vi.fn().mockResolvedValue('"buyer_order_id","name"\r\n"bo-one","Ada Lovelace"\r\n');
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, text });
    vi.stubGlobal("fetch", fetchMock);
    show();

    await screen.findByRole("heading", { name: "Captured orders" });
    fireEvent.click(screen.getByRole("button", { name: "Shipping CSV" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8000/api/v1/merchant/lots/lot-funded/fulfillment");
    expect(init).toMatchObject({ credentials: "include", headers: { Accept: "text/csv" } });
    await waitFor(() => expect(downloads).toContain("fulfillment-lot-funded.csv"));
    // The bytes are the API's CSV, not a file rebuilt from the JSON rows.
    expect(text).toHaveBeenCalledTimes(1);
    expect(await screen.findByText(/Shipping CSV downloaded\./)).toBeInTheDocument();
    expect(screen.queryByText(/downloaded for \d+ captured orders/)).not.toBeInTheDocument();
  });

  it("asks for an inline confirmation before recording shipments", async () => {
    transport.post.mockResolvedValue({
      data: {
        accepted: 1,
        rows: [
          { buyer_order_id: "bo-one", status: "RECORDED", paypal_tracker_status: "SUBMITTED" },
          { buyer_order_id: "bo-two", status: "INVALID", paypal_tracker_status: null },
        ],
      },
    });
    show();

    await screen.findByRole("heading", { name: "Captured orders" });
    fireEvent.click(screen.getByRole("checkbox", { name: "Select order bo-one" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Select order bo-two" }));
    fireEvent.change(screen.getByLabelText("Carrier for bo-one"), { target: { value: "UPS" } });
    fireEvent.change(screen.getByLabelText("Tracking number for bo-one"), {
      target: { value: "1Z999" },
    });
    fireEvent.change(screen.getByLabelText("Carrier for bo-two"), { target: { value: "USPS" } });
    fireEvent.change(screen.getByLabelText("Tracking number for bo-two"), {
      target: { value: "9400" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Record shipments" }));

    expect(transport.post).not.toHaveBeenCalled();
    expect(screen.getByText(/Nothing is sent until you confirm/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Keep editing" }));
    expect(transport.post).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Record shipments" })).toBeInTheDocument();
  });

  it("records the selected shipments and reports each row and its tracker answer", async () => {
    transport.post.mockResolvedValue({
      data: {
        accepted: 1,
        rows: [
          { buyer_order_id: "bo-one", status: "RECORDED", paypal_tracker_status: "SUBMITTED" },
          { buyer_order_id: "bo-two", status: "INVALID", paypal_tracker_status: null },
        ],
      },
    });
    show();

    await screen.findByRole("heading", { name: "Captured orders" });
    fireEvent.click(screen.getByRole("checkbox", { name: "Select order bo-one" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Select order bo-two" }));
    fireEvent.change(screen.getByLabelText("Carrier for bo-one"), { target: { value: "UPS" } });
    fireEvent.change(screen.getByLabelText("Tracking number for bo-one"), {
      target: { value: "1Z999" },
    });
    fireEvent.change(screen.getByLabelText("Carrier for bo-two"), { target: { value: "USPS" } });
    fireEvent.change(screen.getByLabelText("Tracking number for bo-two"), {
      target: { value: "9400" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Record shipments" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm 2 shipments with PayPal" }));

    await waitFor(() => expect(transport.post).toHaveBeenCalledTimes(1));
    const [path, init] = transport.post.mock.calls[0] as [
      string,
      { params: { path: { lot_id: string } }; body: { shipments: unknown[] } },
    ];
    expect(path).toBe("/api/v1/merchant/lots/{lot_id}/shipments");
    expect(init.params.path.lot_id).toBe("lot-funded");
    expect(init.body.shipments).toEqual([
      { buyer_order_id: "bo-one", carrier: "UPS", tracking_number: "1Z999" },
      { buyer_order_id: "bo-two", carrier: "USPS", tracking_number: "9400" },
    ]);

    expect(await screen.findByText("Shipment recorded")).toBeInTheDocument();
    expect(screen.getByText(/PayPal tracker submitted/)).toBeInTheDocument();
    expect(screen.getByText("Not recorded")).toBeInTheDocument();
    // The API returns the row's status, not a reason: show that status and claim no more.
    expect(screen.getByText("INVALID")).toBeInTheDocument();
    expect(screen.queryByText(/says why/)).not.toBeInTheDocument();
    expect(await screen.findByText(/1 of 2 shipments recorded/)).toBeInTheDocument();
  });

  it("says tracker not submitted when PayPal tracking was not submitted", async () => {
    transport.post.mockResolvedValue({
      data: {
        accepted: 1,
        rows: [{ buyer_order_id: "bo-one", status: "RECORDED", paypal_tracker_status: null }],
      },
    });
    show();

    await screen.findByRole("heading", { name: "Captured orders" });
    fireEvent.click(screen.getByRole("checkbox", { name: "Select order bo-one" }));
    fireEvent.change(screen.getByLabelText("Carrier for bo-one"), { target: { value: "UPS" } });
    fireEvent.change(screen.getByLabelText("Tracking number for bo-one"), {
      target: { value: "1Z999" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Record shipments" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm 1 shipment with PayPal" }));

    expect(await screen.findByText("Shipment recorded")).toBeInTheDocument();
    expect(await screen.findByText(/tracker not submitted/)).toBeInTheDocument();
    expect(screen.queryByText(/PayPal tracker submitted/)).not.toBeInTheDocument();
  });

  it("downloads the verification manifest as JSON and renders its own instruction", async () => {
    show();

    await screen.findByRole("heading", { name: "Captured orders" });
    fireEvent.click(screen.getByRole("button", { name: "Verification manifest" }));

    await waitFor(() => expect(downloads).toContain("verification-manifest-lot-funded.json"));
    expect(transport.get).toHaveBeenCalledWith(
      "/api/v1/merchant/lots/{lot_id}/verification-manifest",
      { params: { path: { lot_id: "lot-funded" } } },
    );
    expect(
      await screen.findByText(/Verification manifest downloaded: 1 captured order, \$790\.00 USD expected/),
    ).toBeInTheDocument();
    expect(await screen.findByText(manifest.how_to_verify)).toBeInTheDocument();
  });

  it("verifies payments against PayPal and shows each match and mismatch", async () => {
    show();

    await screen.findByRole("heading", { name: "Captured orders" });
    fireEvent.click(screen.getByRole("button", { name: "Verify payments" }));

    expect(await screen.findByText("1 of 2 captures match PayPal")).toBeInTheDocument();
    expect(screen.getByText("$790.00 USD")).toBeInTheDocument();
    expect(screen.getByText("$464.00 USD")).toBeInTheDocument();
    expect(screen.getByText(/Checked .* with a live read of every order from PayPal/)).toBeInTheDocument();
    expect(screen.getByText("Matches")).toBeInTheDocument();
    expect(screen.getByText("Does not match")).toBeInTheDocument();
    const items = screen.getByRole("list", { name: "Captures checked with PayPal" });
    expect(within(items).getAllByRole("listitem")).toHaveLength(2);
    const [, init] = transport.get.mock.calls.find(
      ([called]) => called === "/api/v1/merchant/lots/{lot_id}/verification",
    ) as [string, GetInit];
    expect(init.params?.path?.lot_id).toBe("lot-funded");
  });

  it("says not funded yet with the lot status when the API answers LOT_NOT_FUNDED", async () => {
    server({ fulfillment: notFunded, lotStatus: "FUNDING" });
    show();

    const panel = await screen.findByRole("region", { name: "Not funded yet" });
    expect(within(panel).getByText(/LOT_NOT_FUNDED/)).toBeInTheDocument();
    expect(within(panel).getByText("FUNDING")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Captured orders" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Shipping CSV" })).not.toBeInTheDocument();
  });

  it("keeps a funded lot with no captures honest about the empty row set", async () => {
    server({ fulfillment: { data: [] } });
    show();

    expect(await screen.findByText(/No captured orders yet/)).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});
