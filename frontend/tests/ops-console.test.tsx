import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const transport = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("../src/shared/api/client", () => ({
  api: { GET: transport.get, POST: transport.post },
  API_BASE_URL: "http://localhost:8000",
}));

import { OpsPage } from "../src/ops";

const LOT_ID = "11111111-1111-4111-8111-111111111111";
const POOL_ID = "22222222-2222-4222-8222-222222222222";

const LOT = {
  lot_id: LOT_ID,
  pool_id: POOL_ID,
  status: "CHECKOUT_OPEN",
  seats: 3,
  min_seats: 2,
  award_id: "44444444-4444-4444-8444-444444444444",
  payment_router: "fake",
  payment_mode: "authorize_capture",
};

const ALERTS = [
  {
    kind: "webhook_dead_letter",
    event_id: "event-one",
    paypal_event_id: "WH-DEAD-1",
    event_type: "PAYMENT.CAPTURE.COMPLETED",
    status: "DEAD_LETTER",
    received_at: "2026-11-03T10:00:00Z",
  },
  {
    kind: "lot_past_fund_deadline",
    lot_id: LOT_ID,
    pool_id: POOL_ID,
    fund_deadline_at: "2026-11-03T09:00:00Z",
  },
  {
    kind: "authorization_aged",
    buyer_order_id: "33333333-3333-4333-8333-333333333333",
    paypal_auth_id: "AUTH-AGED-1",
    age_s: 9000,
  },
];

const DEAD_LETTERS = [
  {
    id: "event-one",
    paypal_event_id: "WH-DEAD-1",
    event_type: "PAYMENT.CAPTURE.COMPLETED",
    status: "DEAD_LETTER",
    verified: true,
    verification_detail: "Order not found yet",
    received_at: "2026-11-03T10:00:00Z",
  },
];

function defaultGet(path: string) {
  if (path === "/api/v1/admin/alerts") {
    return Promise.resolve({ data: { alerts: ALERTS, count: ALERTS.length } });
  }
  if (path === "/api/v1/admin/webhooks/dead-letter") {
    return Promise.resolve({ data: { events: DEAD_LETTERS } });
  }
  if (path === "/api/v1/admin/lots/{lot_id}") {
    return Promise.resolve({ data: LOT });
  }
  if (path === "/api/v1/admin/audit/export") {
    return Promise.resolve({ data: { checkpoints: [{ action: "lot.award", hash: "hash-one" }] } });
  }
  return Promise.resolve({ data: null });
}

function show() {
  return render(
    <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <OpsPage />
    </MemoryRouter>,
  );
}

async function lookupLot() {
  fireEvent.change(await screen.findByLabelText("Lot ID"), { target: { value: LOT_ID } });
  fireEvent.click(screen.getByRole("button", { name: "Look up lot" }));
  await screen.findByText(POOL_ID);
}

beforeEach(() => {
  transport.get.mockReset().mockImplementation(defaultGet);
  transport.post.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("the ops console", () => {
  it("renders the lot facts, alerts and dead letters from their own responses", async () => {
    show();

    expect(await screen.findByRole("heading", { level: 1, name: "Ops console" })).toBeInTheDocument();
    expect(await screen.findByText("Webhook dead letter")).toBeInTheDocument();
    expect(screen.getAllByText("Act now").length).toBeGreaterThan(0);
    expect(screen.getByText("Watch")).toBeInTheDocument();
    expect(await screen.findByText("PAYMENT.CAPTURE.COMPLETED")).toBeInTheDocument();
    expect(screen.getByText("Order not found yet")).toBeInTheDocument();
    expect(screen.getByText("Look up lot")).toBeInTheDocument();

    await lookupLot();
    expect(screen.getByText(LOT.award_id)).toBeInTheDocument();
    expect(screen.getByText("3 seats, minimum 2")).toBeInTheDocument();
    expect(screen.getByText("CHECKOUT_OPEN")).toBeInTheDocument();
    expect(screen.getByText("authorize_capture")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Abort lot" })).toBeInTheDocument();
  });

  it("asks twice before aborting and sends exactly one abort request", async () => {
    transport.post.mockResolvedValue({
      data: { lot_id: LOT_ID, status: "FAILING", transition_id: "LS-08" },
    });
    show();
    await lookupLot();

    fireEvent.click(screen.getByRole("button", { name: "Abort lot" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByText("Abort this lot?")).toBeInTheDocument();
    expect(transport.post).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Yes, abort lot" }));
    expect(await screen.findByText("Lot moved to FAILING (LS-08).")).toBeInTheDocument();
    expect(transport.post).toHaveBeenCalledTimes(1);
    expect(transport.post.mock.calls[0]?.[0]).toBe("/api/v1/admin/lots/{lot_id}/abort");
    expect(transport.post.mock.calls[0]?.[1]).toEqual({ params: { path: { lot_id: LOT_ID } } });
  });

  it("shows the MOCK label only while a toggle is armed", async () => {
    transport.post.mockResolvedValue({
      data: { kind: "paypal_mock_response", value: null, ttl_s: 300, labels: ["MOCK"] },
    });
    show();
    await screen.findByRole("heading", { name: "Demo mock toggles" });
    expect(screen.queryAllByText("MOCK")).toHaveLength(0);

    fireEvent.click(screen.getByRole("button", { name: "Arm Mock PayPal response" }));
    expect((await screen.findAllByText("MOCK")).length).toBeGreaterThan(0);
    expect(transport.post).toHaveBeenCalledWith("/api/v1/admin/mock", {
      body: { kind: "paypal_mock_response", value: null, ttl_s: 300 },
    });
  });

  it("says honestly when mock toggles are switched off", async () => {
    transport.post.mockResolvedValue({
      error: { error: { code: "FEATURE_DISABLED", message: "Mock toggles are disabled." } },
    });
    show();
    await screen.findByRole("heading", { name: "Demo mock toggles" });

    fireEvent.click(screen.getByRole("button", { name: "Arm Delay webhooks" }));
    expect(await screen.findByText("FEATURE_DISABLED")).toBeInTheDocument();
    expect(screen.getByText(/switched off on this deployment/)).toBeInTheDocument();
    expect(screen.queryAllByText("MOCK")).toHaveLength(0);
  });

  it("downloads the audit export as audit-export.json", async () => {
    const createObjectURL = vi.fn((_blob: Blob | MediaSource) => "blob:audit-export");
    const revokeObjectURL = vi.fn((_url: string) => undefined);
    URL.createObjectURL = createObjectURL as typeof URL.createObjectURL;
    URL.revokeObjectURL = revokeObjectURL as typeof URL.revokeObjectURL;
    const clicked: { anchor: HTMLAnchorElement | null } = { anchor: null };
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      clicked.anchor = this;
    });

    show();
    await screen.findByRole("heading", { name: "Audit export" });
    fireEvent.click(screen.getByRole("button", { name: "Export audit chain" }));

    expect(await screen.findByText(/Downloaded audit-export\.json with 1 checkpoint\./)).toBeInTheDocument();
    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(clicked.anchor).not.toBeNull();
    expect((clicked.anchor as HTMLAnchorElement).download).toBe("audit-export.json");
    expect((clicked.anchor as HTMLAnchorElement).href).toBe("blob:audit-export");
    const blob = createObjectURL.mock.calls[0]?.[0] as Blob;
    expect(blob.type).toBe("application/json");
    // jsdom's Blob predates Blob.text, so read it the way the browser does.
    const text = await new Promise<string>((resolve) => {
      const reader = new FileReader();
      reader.addEventListener("load", () => resolve(String(reader.result)));
      reader.readAsText(blob);
    });
    expect(text).toContain("lot.award");
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:audit-export");
  });

  it("reports the reconciler's enqueued count", async () => {
    transport.post.mockResolvedValue({ data: { enqueued: 2 } });
    show();
    await screen.findByRole("heading", { name: "Reconciler" });

    fireEvent.click(screen.getByRole("button", { name: "Run reconciler now" }));
    expect(await screen.findByText("Re-queued 2 stale orders.")).toBeInTheDocument();
    expect(transport.post).toHaveBeenCalledWith("/api/v1/admin/reconciler/run");
  });

  it("keeps the other sections usable when the alerts request fails", async () => {
    transport.get.mockImplementation((path: string) => {
      if (path === "/api/v1/admin/alerts") {
        return Promise.resolve({ error: { error: { code: "INTERNAL_ERROR", message: "Alerts are unavailable." } } });
      }
      return defaultGet(path);
    });
    show();

    expect(await screen.findByText("Alerts are unavailable.")).toBeInTheDocument();
    expect(await screen.findByText("PAYMENT.CAPTURE.COMPLETED")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Look up lot" })).toBeInTheDocument();
  });

  it("refuses a malformed lot ID without sending a request", async () => {
    show();
    fireEvent.change(await screen.findByLabelText("Lot ID"), { target: { value: "lot-one" } });
    fireEvent.click(screen.getByRole("button", { name: "Look up lot" }));

    expect(await screen.findByText("VALIDATION_ERROR")).toBeInTheDocument();
    await waitFor(() => {
      expect(transport.get.mock.calls.some(([path]) => path === "/api/v1/admin/lots/{lot_id}")).toBe(false);
    });
  });
});
