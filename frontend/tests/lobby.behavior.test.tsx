import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const transport = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), del: vi.fn() }));
vi.mock("../src/shared/api/client", () => ({
  api: { GET: transport.get, POST: transport.post, DELETE: transport.del },
  API_BASE_URL: "http://localhost:8000",
}));

import { PoolPage } from "../src/buyer/lobby/PoolPage";
import { usdToCents } from "../src/buyer/lobby/money";

const CLOSE_AT = "2026-11-02T10:15:00Z";
const SERVER_NOW = "2026-11-02T10:02:00Z";

const detail = {
  pool_id: "pool-one",
  title: "27-inch 4K monitor",
  status: "OPEN",
  mode: "LIVE_SANDBOX",
  product_key: "monitor-27-4k",
  condition: "NEW",
  variant: "black",
  zone_ids: ["US-EAST"],
  seats: 12,
  min_seats: 6,
  close_at: CLOSE_AT,
  rules_hash: "a".repeat(64),
  template: {
    currency: "USD",
    zones: [{ zone_id: "US-EAST", label: "US East", regions: ["NY", "NJ"] }],
  },
  lot_plan: [{ zone_id: "US-EAST", lots: [{ seats: 8, min_seats: 4 }, { seats: 4, min_seats: 2 }] }],
  timeline: {
    open_at: "2026-11-02T10:00:00Z",
    close_at: CLOSE_AT,
    bid_window_s: 1800,
    offer_window_s: 180,
    fund_deadline_s: 600,
  },
};

const receipt = {
  payload: {
    v: 1,
    commitment: "c".repeat(64),
    entry_id: "entry-one",
    pool_id: "pool-one",
    received_at: "2026-11-02T10:03:00.000000Z",
  },
  salt_hex: "s".repeat(64),
  request_hash: "r".repeat(64),
  signature: "sig-base64url",
};

class FakeSource {
  static instances: FakeSource[] = [];
  listeners: Record<string, ((event: { data: string }) => void)[]> = {};
  closed = false;
  constructor(public url: string) {
    FakeSource.instances.push(this);
  }
  addEventListener(kind: string, fn: (event: { data: string }) => void): void {
    (this.listeners[kind] ??= []).push(fn);
  }
  removeEventListener(kind: string, fn: (event: { data: string }) => void): void {
    this.listeners[kind] = (this.listeners[kind] ?? []).filter((item) => item !== fn);
  }
  close(): void {
    this.closed = true;
  }
  emit(kind: string, data: Record<string, unknown>): void {
    for (const fn of this.listeners[kind] ?? []) fn({ data: JSON.stringify(data) });
  }
}

function show() {
  return render(
    <MemoryRouter
      future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      initialEntries={["/pools/pool-one"]}
    >
      <Routes>
        <Route path="/pools/:poolId" element={<PoolPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  // jsdom has no top layer; native focus containment is checked in the browser.
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", { configurable: true, value() { this.setAttribute("open", ""); } });
  Object.defineProperty(HTMLDialogElement.prototype, "close", { configurable: true, value() { this.removeAttribute("open"); } });
  sessionStorage.clear();
  FakeSource.instances = [];
  vi.stubGlobal("EventSource", FakeSource);
  transport.get.mockReset().mockImplementation((path: string) => {
    if (path === "/api/v1/pools/{pool_id}") return Promise.resolve({ data: detail });
    if (path === "/api/v1/pools/{pool_id}/entries/me") return Promise.resolve({ error: { error: { code: "NOT_FOUND" } } });
    return Promise.resolve({ data: null });
  });
  transport.post.mockReset();
  transport.del.mockReset();
});

afterEach(() => {
  cleanup();
  Reflect.deleteProperty(HTMLDialogElement.prototype, "showModal");
  Reflect.deleteProperty(HTMLDialogElement.prototype, "close");
  vi.unstubAllGlobals();
});

describe("the money rule at the browser edge", () => {
  it("reads a USD amount as integer cents and refuses anything else", () => {
    expect(usdToCents("600")).toBe(60000);
    expect(usdToCents("600.00")).toBe(60000);
    expect(usdToCents("600.5")).toBe(60050);
    expect(usdToCents(" 600.25 ")).toBe(60025);
    expect(usdToCents("600.255")).toBeNull();
    expect(usdToCents("$600")).toBeNull();
    expect(usdToCents("6e2")).toBeNull();
    expect(usdToCents("")).toBeNull();
  });
});

describe("the pool lobby", () => {
  it("puts the recorded outcome before product details and removes obsolete entry-window emphasis", async () => {
    transport.get.mockImplementation((path: string) => Promise.resolve(path.endsWith("/entries/me")
      ? { data: { entry_id: "entry-one", entry_status: "ELIGIBLE", receipt, allocation: { status: "SEATED", rank: 4, zone_id: "US-EAST", lot_id: "lot-one" } } }
      : { data: { ...detail, status: "RUNNING" } }));
    show();
    const outcome = await screen.findByText("Seat allocated");
    const product = screen.getByRole("region", { name: "Product overview" });
    expect(outcome.compareDocumentPosition(product) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.queryByText("Entry window")).toBeNull();
    expect(screen.queryByText("entry-one")).toBeNull();
    expect(screen.queryByText(/Merchants are submitting sealed bids/)).toBeNull();
    expect(screen.queryByText(/The pool decides seats after it closes/)).toBeNull();
    expect(screen.getByRole("button", { name: "View entry receipt" })).toBeInTheDocument();
  });
  it("provides direct entry and public audit shortcuts", async () => {
    show();
    expect(await screen.findByRole("link", { name: "Your entry" })).toHaveAttribute("href", "#pool-entry");
    expect(screen.getByRole("link", { name: "Public audit" })).toHaveAttribute("href", "/audit/pool-one");
    expect(document.getElementById("pool-entry")).toHaveAccessibleName("Your place in this pool");
  });
  it("places the entry action before the supporting timeline in reading order", async () => {
    show();
    const join = await screen.findByRole("heading", { name: "State your request" });
    const timeline = screen.getByText("How this pool runs", { selector: "summary" });
    expect(join.compareDocumentPosition(timeline) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
  it("describes the cap in delivered dollars and associates the help with the field", async () => {
    show();
    const cap = await screen.findByLabelText("Your maximum total, in USD");
    fireEvent.change(cap, { target: { value: "600.25" } });
    expect(cap).toHaveAccessibleDescription(/\$600\.25 USD.*delivery/i);
    expect(screen.queryByText(/60025 cents/)).toBeNull();
  });

  it("uses the server's delivery date to guide manual entry without choosing a buyer deadline", async () => {
    transport.get.mockImplementation((path: string) => Promise.resolve(path.endsWith("/entries/me")
      ? { error: { error: { code: "NOT_FOUND" } } }
      : { data: { ...detail, latest_delivery: "2026-12-07" } }));
    show();
    const needed = await screen.findByLabelText("Needed by");
    expect(needed).toHaveAttribute("min", "2026-12-07");
    expect(needed).toHaveValue("");
    expect(needed).toHaveAccessibleDescription(/December 7, 2026 or later/);
  });

  it("does not promise every waitlisted buyer the next vacant seat", async () => {
    transport.get.mockImplementation((path: string) => Promise.resolve(path.endsWith("/entries/me")
      ? { data: { entry_id: "waiting", entry_status: "ELIGIBLE", allocation: { status: "WAITLISTED", rank: 20, waitlist_position: 8, zone_id: "US-EAST", lot_id: null } } }
      : { data: detail }));
    show();
    expect(await screen.findByText("Position #8")).toBeInTheDocument();
    expect(screen.getByText(/published waitlist order/i)).toBeInTheDocument();
    expect(screen.queryByText(/transfers automatically to you/i)).toBeNull();
  });

  it("opens the receipt as a native modal and restores focus after Escape", async () => {
    transport.get.mockImplementation((path: string) => Promise.resolve(path.endsWith("/entries/me")
      ? { data: { entry_id: "entry-one", entry_status: "SUBMITTED", receipt } }
      : { data: detail }));
    show();
    const opener = await screen.findByRole("button", { name: "View entry receipt" });
    opener.focus();
    fireEvent.click(opener);
    const dialog = await screen.findByRole("dialog", { name: "Entry receipt modal" });
    expect(dialog.tagName).toBe("DIALOG");
    expect(dialog).toHaveAttribute("open");
    fireEvent(dialog, new Event("cancel", { cancelable: true }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(opener).toHaveFocus();
  });
  it("never offers Join while the buyer entry is still being checked", async () => {
    let finish!: (value: unknown) => void;
    transport.get.mockImplementation((path: string) => path.endsWith("/entries/me")
      ? new Promise((resolve) => { finish = resolve; }) : Promise.resolve({ data: detail }));
    show();
    expect(await screen.findByRole("status", { name: "Checking your entry" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Join/ })).toBeNull();
    await act(async () => finish({ data: { entry_id: "entry-one", entry_status: "SUBMITTED", receipt } }));
    expect(await screen.findByRole("heading", { name: "Your entry" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Join/ })).toBeNull();
  });
  it("does not mistake a failed entry lookup for permission to join", async () => {
    transport.get.mockImplementation((path: string) => Promise.resolve(path.endsWith("/entries/me")
      ? { error: { error: { code: "INTERNAL_ERROR" } } } : { data: detail }));
    show();
    expect(await screen.findByRole("button", { name: "Retry entry check" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Join/ })).toBeNull();
  });
  it("states the deadline in absolute terms until the feed gives a server sample", async () => {
    show();
    const strip = await screen.findByText("Entry window");
    expect(strip.parentElement?.parentElement?.textContent).toContain("UTC");
    expect(screen.queryByText("Entry window closes in")).not.toBeInTheDocument();

    const source = FakeSource.instances[0];
    expect(source?.url).toBe("http://localhost:8000/api/v1/pools/pool-one/events");
    act(() => source?.emit("tick", { server_time: SERVER_NOW }));
    expect(await screen.findByText("Entry window closes in")).toBeInTheDocument();
    expect(screen.getByText("13:00")).toBeInTheDocument();
  });

  it("follows the pool's own status and reports a lot status only when the feed says so", async () => {
    show();
    await screen.findByRole("heading", { level: 1, name: "27-inch 4K monitor" });
    expect(screen.queryByText("Live lot references")).not.toBeInTheDocument();
    expect(screen.getByText("8 places")).toBeInTheDocument();
    expect(screen.getByText("Minimum 4 buyers")).toBeInTheDocument();
    expect(screen.getByText("4 places")).toBeInTheDocument();
    expect(screen.getByText("Minimum 2 buyers")).toBeInTheDocument();

    const source = FakeSource.instances[0];
    act(() => source?.emit("pool_status", { pool_id: "pool-one", status: "ALLOCATED" }));
    expect(await screen.findByText("ALLOCATED")).toBeInTheDocument();
    act(() => source?.emit("lot_status", { pool_id: "pool-one", lot_id: "lot-one", status: "BIDDING" }));
    fireEvent.click(await screen.findByText("Live lot references"));
    expect(screen.getByText("Bidding")).toBeInTheDocument();
  });

  it("joins through the manual form and lands on the receipt", async () => {
    // The join response is not what the screen shows any more: after the join the lobby
    // re-reads the entry, and that read carries the signed receipt (CR-9).
    let entered = false;
    transport.get.mockImplementation((path: string) => {
      if (path === "/api/v1/pools/{pool_id}") return Promise.resolve({ data: detail });
      if (path === "/api/v1/pools/{pool_id}/entries/me") {
        return Promise.resolve(
          entered
            ? { data: { entry_id: "entry-one", entry_status: "SUBMITTED", receipt } }
            : { error: { error: { code: "NOT_FOUND" } } },
        );
      }
      return Promise.resolve({ error: { error: { code: "NOT_FOUND" } } });
    });
    transport.post
      .mockImplementationOnce(() =>
        Promise.resolve({ data: { confirmed_request_id: "request-one", canonical_request: {} } }),
      )
      .mockImplementationOnce(() => {
        entered = true;
        return Promise.resolve({
          data: { entry_id: "entry-one", already_entered: false, pool_status: "OPEN", receipt },
        });
      });
    show();
    await screen.findByRole("heading", { level: 1, name: "27-inch 4K monitor" });
    fireEvent.change(screen.getByLabelText("Delivery region"), { target: { value: "NY" } });
    fireEvent.change(screen.getByLabelText("Needed by"), { target: { value: "2026-11-30" } });
    fireEvent.change(screen.getByLabelText("Your maximum total, in USD"), {
      target: { value: "600" },
    });
    expect(screen.getByLabelText("Your maximum total, in USD")).toHaveAccessibleDescription(/\$600\.00 USD/);
    fireEvent.click(screen.getByRole("button", { name: "Confirm and join" }));

    expect(await screen.findByRole("heading", { name: "Your entry" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Entry receipt" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "View entry receipt" }));
    expect(await screen.findByRole("heading", { name: "Entry receipt" })).toBeInTheDocument();
    const [manualPath, manualInit] = transport.post.mock.calls[0] ?? [];
    expect(manualPath).toBe("/api/v1/intake/manual");
    expect(manualInit).toEqual({
      body: {
        pool_id: "pool-one",
        delivery: { region: "NY" },
        required_by: "2026-11-30",
        max_total_cents: 60000,
        firm: [],
        preferences: [],
      },
    });
    const [joinPath, joinInit] = transport.post.mock.calls[1] ?? [];
    expect(joinPath).toBe("/api/v1/pools/{pool_id}/entries");
    expect(joinInit).toEqual({
      params: { path: { pool_id: "pool-one" }, header: { "Idempotency-Key": "request-one" } },
      body: { confirmed_request_id: "request-one" },
    });
    // The receipt is the server's record, not a browser copy.
    expect(sessionStorage.getItem("fairpool.entry.receipt.pool-one")).toBeNull();
  });

  it("joins a confirmed request without confirming a second one", async () => {
    sessionStorage.setItem("fairpool.entry.pending.pool-one", '"request-two"');
    let entered = false;
    transport.get.mockImplementation((path: string) => {
      if (path === "/api/v1/pools/{pool_id}") return Promise.resolve({ data: detail });
      if (path === "/api/v1/pools/{pool_id}/entries/me") {
        return Promise.resolve(
          entered
            ? { data: { entry_id: "entry-one", entry_status: "SUBMITTED", receipt } }
            : { error: { error: { code: "NOT_FOUND" } } },
        );
      }
      return Promise.resolve({ error: { error: { code: "NOT_FOUND" } } });
    });
    transport.post.mockImplementation(() => {
      entered = true;
      return Promise.resolve({
        data: { entry_id: "entry-one", already_entered: false, pool_status: "OPEN", receipt },
      });
    });
    show();
    fireEvent.click(await screen.findByRole("button", { name: "Join this pool" }));
    expect(await screen.findByRole("heading", { name: "Your entry" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Entry receipt" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "View entry receipt" }));
    expect(await screen.findByRole("heading", { name: "Entry receipt" })).toBeInTheDocument();
    expect(transport.post).toHaveBeenCalledTimes(1);
    expect(transport.post.mock.calls[0]?.[0]).toBe("/api/v1/pools/{pool_id}/entries");
  });

  it("keeps the same request when the join fails, so a retry cannot double-confirm", async () => {
    transport.post
      .mockResolvedValueOnce({
        data: { confirmed_request_id: "request-one", canonical_request: {} },
      })
      .mockResolvedValueOnce({
        error: { error: { code: "POOL_CLOSED", message: "The entry window has closed." } },
      });
    let entered = false;
    transport.get.mockImplementation((path: string) => {
      if (path === "/api/v1/pools/{pool_id}") return Promise.resolve({ data: detail });
      if (path === "/api/v1/pools/{pool_id}/entries/me") {
        return Promise.resolve(
          entered
            ? { data: { entry_id: "entry-one", entry_status: "SUBMITTED", receipt } }
            : { error: { error: { code: "NOT_FOUND" } } },
        );
      }
      return Promise.resolve({ error: { error: { code: "NOT_FOUND" } } });
    });
    show();
    await screen.findByRole("heading", { level: 1, name: "27-inch 4K monitor" });
    fireEvent.change(screen.getByLabelText("Delivery region"), { target: { value: "NY" } });
    fireEvent.change(screen.getByLabelText("Needed by"), { target: { value: "2026-11-30" } });
    fireEvent.change(screen.getByLabelText("Your maximum total, in USD"), {
      target: { value: "600" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Confirm and join" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("POOL_CLOSED");
    expect(sessionStorage.getItem("fairpool.entry.pending.pool-one")).toBe('"request-one"');

    transport.post.mockImplementationOnce(() => {
      entered = true;
      return Promise.resolve({
        data: { entry_id: "entry-one", already_entered: false, pool_status: "OPEN", receipt },
      });
    });
    fireEvent.click(screen.getByRole("button", { name: "Join this pool" }));
    await waitFor(() => expect(transport.post).toHaveBeenCalledTimes(3));
    // The retry is the join alone: no second intake/manual call.
    expect(transport.post.mock.calls[2]?.[0]).toBe("/api/v1/pools/{pool_id}/entries");
  });

  it("refuses a money amount the contract does not accept before anything is sent", async () => {
    show();
    await screen.findByRole("heading", { level: 1, name: "27-inch 4K monitor" });
    fireEvent.change(screen.getByLabelText("Your maximum total, in USD"), {
      target: { value: "600.255" },
    });
    expect(screen.getByText("Use digits, with up to two decimals: 600 or 600.00.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Confirm and join" })).toBeDisabled();
    expect(transport.post).not.toHaveBeenCalled();
  });

  it("shows the buyer's own entry state and withdraws it only after a second click", async () => {
    transport.get.mockImplementation((path: string) => {
      if (path === "/api/v1/pools/{pool_id}") return Promise.resolve({ data: detail });
      if (path === "/api/v1/pools/{pool_id}/entries/me") {
        return Promise.resolve({
          data: { entry_id: "entry-one", entry_status: "SUBMITTED", receipt },
        });
      }
      return Promise.resolve({ error: { error: { code: "NOT_FOUND" } } });
    });
    transport.del.mockResolvedValue({ data: { entry_id: "entry-one", entry_status: "WITHDRAWN" } });
    show();
    expect(await screen.findByRole("heading", { name: "Your entry" })).toBeInTheDocument();
    expect(screen.getByText("Entry received")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "View entry receipt" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Withdraw my entry" }));
    expect(transport.del).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Withdraw entry" }));
    await waitFor(() => expect(transport.del).toHaveBeenCalledTimes(1));
    expect(transport.del.mock.calls[0]?.[0]).toBe("/api/v1/pools/{pool_id}/entries/me");
    expect(transport.del.mock.calls[0]?.[1]).toEqual({
      params: { path: { pool_id: "pool-one" } },
    });
    // The status after a withdraw is re-read from the server, never written here.
    await waitFor(() => expect(transport.get).toHaveBeenCalledTimes(3));
  });

  it("states a closed pool as closed and disables the join", async () => {
    transport.get.mockImplementation((path: string) => {
      if (path === "/api/v1/pools/{pool_id}") {
        return Promise.resolve({ data: { ...detail, status: "CLOSED", close_at: null } });
      }
      return Promise.resolve({ error: { error: { code: "NOT_FOUND" } } });
    });
    show();
    expect(
      await screen.findByText("This pool is closed, so no new entry can be recorded."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Confirm and join" })).toBeDisabled();
    expect(screen.queryByText("Entry window")).toBeNull();
  });

  it("stops offering a join once the entry window has passed its close time", async () => {
    // The pool is still OPEN (no worker has closed it), but the deadline is behind the
    // server's own clock: the screen must not offer an action the server will refuse.
    transport.get.mockImplementation((path: string) => {
      if (path === "/api/v1/pools/{pool_id}") {
        return Promise.resolve({ data: { ...detail, close_at: "2026-11-02T10:20:00Z" } });
      }
      return Promise.resolve({ error: { error: { code: "NOT_FOUND" } } });
    });
    show();
    await screen.findByRole("heading", { level: 1, name: "27-inch 4K monitor" });
    const source = FakeSource.instances[0];
    act(() => source?.emit("tick", { server_time: SERVER_NOW }));
    expect(await screen.findByText("Entry window closes in")).toBeInTheDocument();

    act(() => source?.emit("tick", { server_time: "2026-11-02T10:21:00Z" }));
    expect(
      await screen.findByText("The entry window has passed its close time, so no new entry can be recorded."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Confirm and join" })).toBeDisabled();
  });

  it("opens the published rules on demand and shows their hash", async () => {
    transport.get.mockImplementation((path: string) => {
      if (path === "/api/v1/pools/{pool_id}") return Promise.resolve({ data: detail });
      if (path === "/api/v1/pools/{pool_id}/rules") {
        return Promise.resolve({ data: { rules_document: { allocation: "seeded_lottery_v1" }, rules_hash: "a".repeat(64) } });
      }
      return Promise.resolve({ error: { error: { code: "NOT_FOUND" } } });
    });
    show();
    await screen.findByRole("heading", { level: 1, name: "27-inch 4K monitor" });
    expect(transport.get.mock.calls.some(([path]) => path === "/api/v1/pools/{pool_id}/rules")).toBe(
      false,
    );
    fireEvent.click(screen.getByText("Pool rules and their hash"));
    expect(await screen.findByText("Seeded lottery")).toBeInTheDocument();
    expect(screen.queryByText(/"allocation":/)).toBeNull();
    expect(screen.getByText("a".repeat(64))).toBeInTheDocument();
  });

  it("has no page for a pool that is not published", async () => {
    transport.get.mockResolvedValue({
      error: { error: { code: "NOT_FOUND", message: "Unknown resource." } },
    });
    show();
    expect(await screen.findByRole("heading", { name: "Pool not found" })).toBeInTheDocument();
    expect(
      screen.getByText(/This pool has no public page/),
    ).toBeInTheDocument();
  });

  it("closes the feed when the screen leaves", async () => {
    const view = show();
    await screen.findByRole("heading", { level: 1, name: "27-inch 4K monitor" });
    const source = FakeSource.instances[0];
    expect(source?.closed).toBe(false);
    view.unmount();
    expect(source?.closed).toBe(true);
  });

  it("labels a simulated pool instead of presenting it as live", async () => {
    transport.get.mockImplementation((path: string) => {
      if (path === "/api/v1/pools/{pool_id}") {
        return Promise.resolve({ data: { ...detail, mode: "SIMULATION" } });
      }
      return Promise.resolve({ error: { error: { code: "NOT_FOUND" } } });
    });
    show();
    expect(await screen.findByText("SIMULATED")).toBeInTheDocument();
  });
});
