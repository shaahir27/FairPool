import { createHash } from "node:crypto";

import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const transport = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), delete: vi.fn() }));
vi.mock("../src/shared/api/client", () => ({
  api: { GET: transport.get, POST: transport.post, DELETE: transport.delete },
  API_BASE_URL: "http://localhost:8000",
}));

import { AreaLayout, setAccount } from "../src/shared";
import { AgentSettingsPage, PayPalSettingsPage } from "../src/buyer/pages";

beforeEach(() => {
  setAccount(null);
  transport.get.mockReset();
  transport.post.mockReset();
  transport.delete.mockReset();
  vi.restoreAllMocks();
});

afterEach(() => {
  vi.useRealTimers();
});

it("starts with connections and a single setup action, keeping manual fields out of the way", async () => {
  transport.get.mockImplementation(async (path: string) => ({data: path === "/api/v1/pools" ? [] : {items: []}}));
  render(<MemoryRouter><AgentSettingsPage /></MemoryRouter>);
  expect(await screen.findByRole("heading", {name: "Agent connections"})).toBeInTheDocument();
  expect(screen.getByRole("button", {name: "Connect an agent"})).toBeEnabled();
  expect(screen.queryByLabelText("Maximum per entry (USD)")).toBeNull();
  expect(screen.queryByRole("button", {name: "Create delegation"})).toBeNull();
  expect(screen.getByRole("button", {name: "Set up manually"})).toBeEnabled();
});

it("prepares access from intent without asking the buyer to search pools or accept an unstated default cap", async () => {
  const id = "11111111-1111-4111-8111-111111111111";
  transport.get.mockImplementation(async (path: string) => ({data: path === "/api/v1/pools" ? [{pool_id: id, title: "Monitor pool"}] : {items: []}}));
  transport.post.mockResolvedValue({data: {source: "ai", pool_ids: [id], category: null, max_cap_cents: 100000, expires_at: "2099-01-01T23:59:59Z", conditions: [], reserved: ["payment_approval"], clarifying_question: null}});
  render(<MemoryRouter><AgentSettingsPage /></MemoryRouter>);
  fireEvent.click(screen.getByRole("button", {name: "Set up manually"}));
  expect(screen.queryByRole("checkbox", {name: "Monitor pool"})).toBeNull();
  fireEvent.change(screen.getByLabelText("Describe your mandate"), {target: {value: "Find a monitor under $1000 until 1 January 2099"}});
  fireEvent.click(screen.getByRole("button", {name: "Propose with AI"}));
  await waitFor(() => expect(transport.post).toHaveBeenCalledWith("/api/v1/me/mandate-proposal", {body: {message: "Find a monitor under $1000 until 1 January 2099", pool_ids: [], max_cap_cents: null}}));
  expect(await screen.findByTestId("mandate-text")).toHaveTextContent("Monitor pool");
  expect(screen.getByTestId("mandate-text")).toHaveTextContent("1000.00");
  expect(screen.getByRole("checkbox", {name: /I approve this mandate/})).not.toBeChecked();
  expect(transport.post.mock.calls.every(([path]) => path === "/api/v1/me/mandate-proposal")).toBe(true);
});

it("hydrates an automatically matched pool outside the initial catalogue before review", async () => {
  transport.get.mockImplementation(async (path: string) => ({data: path === "/api/v1/pools" ? [] : path === "/api/v1/pools/{pool_id}" ? {pool_id: "matched", title: "January dock pool", status: "OPEN"} : {items: []}}));
  transport.post.mockResolvedValue({data: {source: "ai", pool_ids: ["matched"], category: null, max_cap_cents: 10000, expires_at: "2099-01-01T23:59:59Z", conditions: []}});
  render(<MemoryRouter><AgentSettingsPage /></MemoryRouter>);
  fireEvent.click(screen.getByRole("button", {name: "Set up manually"}));
  fireEvent.change(screen.getByLabelText("Describe your mandate"), {target: {value: "Find a dock under $100"}});
  fireEvent.click(screen.getByRole("button", {name: "Propose with AI"}));
  expect(await screen.findByTestId("mandate-text")).toHaveTextContent("January dock pool");
  expect(transport.get).toHaveBeenCalledWith("/api/v1/pools/{pool_id}", {params: {path: {pool_id: "matched"}}});
  expect(screen.getByRole("button", {name: "Create delegation"})).toBeEnabled();
});

function showManual() {
  render(<MemoryRouter><AgentSettingsPage /></MemoryRouter>);
  fireEvent.click(screen.getByRole("button", {name: "Set up manually"}));
  fireEvent.click(screen.getByRole("button", {name: "Choose fields myself"}));
}

it("shows the PayPal link state and revokes it after a confirmation", async () => {
  transport.get.mockResolvedValue({ data: { paypal_linked: true } });
  transport.delete.mockResolvedValue({ data: { paypal_linked: false } });
  render(<MemoryRouter><PayPalSettingsPage /></MemoryRouter>);

  expect(await screen.findByText("A PayPal account is linked.")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Revoke the link" }));
  expect(transport.delete).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", {name: "Confirm revoke link"}));

  await waitFor(() => expect(transport.delete).toHaveBeenCalledWith("/api/v1/paypal/link"));
  expect(await screen.findByText("No PayPal account is linked yet.")).toBeInTheDocument();
});

it("revokes nothing when the confirmation is cancelled", async () => {
  transport.get.mockResolvedValue({ data: { paypal_linked: true } });
  render(<MemoryRouter><PayPalSettingsPage /></MemoryRouter>);

  fireEvent.click(await screen.findByRole("button", { name: "Revoke the link" }));
  fireEvent.click(screen.getByRole("button", {name: "Keep linked"}));

  expect(transport.delete).not.toHaveBeenCalled();
  expect(screen.getByText("A PayPal account is linked.")).toBeInTheDocument();
  await waitFor(() => expect(screen.getByRole("button", {name: "Revoke the link"})).toHaveFocus());
});

it("opens PayPal in a popup when linking", async () => {
  transport.get.mockImplementation((path: string) => {
    if (path === "/api/v1/paypal/login/start") {
      return Promise.resolve({ data: { authorize_url: "https://www.sandbox.paypal.com/checkoutnow?token=abc" } });
    }
    return Promise.resolve({ data: { paypal_linked: false } });
  });
  const popup = { close: vi.fn() } as unknown as Window;
  const open = vi.spyOn(window, "open").mockReturnValue(popup);
  render(<MemoryRouter><PayPalSettingsPage /></MemoryRouter>);

  fireEvent.click(await screen.findByRole("button", { name: "Link PayPal" }));
  await waitFor(() => expect(open).toHaveBeenCalledWith(
    "https://www.sandbox.paypal.com/checkoutnow?token=abc",
    "fairpool-paypal-link",
    expect.any(String),
  ));
});

it("never opens an authorize_url outside the PayPal sandbox host", async () => {
  transport.get.mockImplementation((path: string) => {
    if (path === "/api/v1/paypal/login/start") {
      return Promise.resolve({
        data: { authorize_url: "https://www.sandbox.paypal.com.example.test/checkoutnow?token=abc" },
      });
    }
    return Promise.resolve({ data: { paypal_linked: false } });
  });
  const open = vi.spyOn(window, "open");
  render(<MemoryRouter><PayPalSettingsPage /></MemoryRouter>);

  fireEvent.click(await screen.findByRole("button", { name: "Link PayPal" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("REQUEST_FAILED");
  expect(open).not.toHaveBeenCalled();
});

it("stops the link poll on unmount and closes the popup", async () => {
  transport.get.mockImplementation((path: string) => {
    if (path === "/api/v1/paypal/login/start") {
      return Promise.resolve({ data: { authorize_url: "https://www.sandbox.paypal.com/checkoutnow?token=abc" } });
    }
    return Promise.resolve({ data: { paypal_linked: false } });
  });
  const popup = { close: vi.fn(), closed: false } as unknown as Window;
  vi.spyOn(window, "open").mockReturnValue(popup);
  const view = render(<MemoryRouter><PayPalSettingsPage /></MemoryRouter>);
  await screen.findByRole("button", { name: "Link PayPal" });
  vi.useFakeTimers();
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Link PayPal" }));
  });
  expect(window.open).toHaveBeenCalled();

  view.unmount();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(10_000);
  });

  // The initial /me read and the login/start call, and nothing the cleared poll would add.
  expect(transport.get).toHaveBeenCalledTimes(2);
  expect(popup.close).toHaveBeenCalled();
});

it("closes the PayPal popup and reports a timeout instead of polling forever", async () => {
  transport.get.mockImplementation((path: string) => {
    if (path === "/api/v1/paypal/login/start") {
      return Promise.resolve({ data: { authorize_url: "https://www.sandbox.paypal.com/checkoutnow?token=abc" } });
    }
    return Promise.resolve({ data: { paypal_linked: false } });
  });
  const popup = { close: vi.fn(), closed: false } as unknown as Window;
  vi.spyOn(window, "open").mockReturnValue(popup);
  render(<MemoryRouter><PayPalSettingsPage /></MemoryRouter>);
  await screen.findByRole("button", { name: "Link PayPal" });
  vi.useFakeTimers();
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Link PayPal" }));
  });

  await act(async () => {
    await vi.advanceTimersByTimeAsync(122_000);
  });

  expect(popup.close).toHaveBeenCalled();
  expect(screen.getByRole("alert")).toHaveTextContent(/PayPal did not complete the connection/);
  const calls = transport.get.mock.calls.length;
  await act(async () => {
    await vi.advanceTimersByTimeAsync(10_000);
  });
  expect(transport.get.mock.calls.length).toBe(calls);
});

it("stops polling when the user closes the PayPal popup", async () => {
  transport.get.mockImplementation((path: string) => {
    if (path === "/api/v1/paypal/login/start") {
      return Promise.resolve({ data: { authorize_url: "https://www.sandbox.paypal.com/checkoutnow?token=abc" } });
    }
    return Promise.resolve({ data: { paypal_linked: false } });
  });
  const popup = { close: vi.fn(), closed: false } as unknown as Window;
  vi.spyOn(window, "open").mockReturnValue(popup);
  render(<MemoryRouter><PayPalSettingsPage /></MemoryRouter>);
  await screen.findByRole("button", { name: "Link PayPal" });
  vi.useFakeTimers();
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Link PayPal" }));
  });

  (popup as { closed: boolean }).closed = true;
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1_500);
  });

  expect(screen.getByRole("alert")).toHaveTextContent(/PayPal window closed/);
  const calls = transport.get.mock.calls.length;
  await act(async () => {
    await vi.advanceTimersByTimeAsync(5_000);
  });
  expect(transport.get.mock.calls.length).toBe(calls);
});

it("offers a retry when the PayPal link state cannot be loaded", async () => {
  transport.get
    .mockResolvedValueOnce({ error: { error: { code: "REQUEST_FAILED", message: "No account." } } })
    .mockResolvedValueOnce({ data: { paypal_linked: true } });
  render(<MemoryRouter><PayPalSettingsPage /></MemoryRouter>);

  expect(await screen.findByRole("alert")).toHaveTextContent("No account.");
  expect(screen.queryByText("Checking your PayPal link…")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Check again" }));

  expect(await screen.findByText("A PayPal account is linked.")).toBeInTheDocument();
});

it("includes pools beyond the default page when choosing an agent scope", async () => {
  const pools = Array.from({ length: 21 }, (_, index) => ({
    pool_id: `scope-${index}`, title: index === 20 ? "January dock pool" : `Earlier pool ${index}`,
    status: "OPEN",
  }));
  transport.get.mockImplementation((path, init) => Promise.resolve({
    data: path === "/api/v1/pools"
      ? pools.slice(0, init?.params?.query?.limit ?? 20)
      : { items: [] },
  }));
  showManual();
  expect(await screen.findByRole("checkbox", { name: /January dock pool/ })).toBeInTheDocument();
});

it("creates a scoped delegation, shows the token once and lists it", async () => {
  const pool = { pool_id: "11111111-1111-4111-8111-111111111111", title: "Demo monitor pool" };
  transport.get.mockImplementation((path: string) => {
    if (path === "/api/v1/me/delegations") {
      return Promise.resolve({ data: { items: [{
        id: "22222222-2222-4222-8222-222222222222",
        scope: { pool_ids: [pool.pool_id], category: null },
        max_cap_cents: 60000,
        expires_at: "2026-12-01T00:00:00Z",
        revoked_at: null,
      }] } });
    }
    if (path === "/api/v1/pools") return Promise.resolve({ data: [{ ...pool, status: "OPEN" }] });
    return Promise.resolve({ data: {} });
  });
  transport.post.mockResolvedValue({ data: { token: "fpd_abc_secret", id: "33333333-3333-4333-8333-333333333333" } });
  showManual();

  const checkbox = await screen.findByRole("checkbox", { name: /Demo monitor pool/ });
  fireEvent.click(checkbox);
  fireEvent.click(screen.getByRole("checkbox", { name: /I approve this mandate/ }));
  fireEvent.click(screen.getByRole("button", { name: "Create delegation" }));

  await waitFor(() => expect(transport.post).toHaveBeenCalledWith("/api/v1/me/delegations", {
    body: expect.objectContaining({ max_cap_cents: 60000, scope: expect.objectContaining({ pool_ids: [pool.pool_id] }) }),
  }));
  expect(await screen.findByText("Copy this token now. It is shown once.")).toBeInTheDocument();
  expect(screen.getByText("fpd_abc_secret")).toBeInTheDocument();
  const list = screen.getByRole("heading", { name: "Connections" }).closest<HTMLElement>(".settings-delegations")!;
  expect(within(list).getByText(/1 pool/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", {name: "Hide token"}));
  expect(screen.queryByText("fpd_abc_secret")).toBeNull();
});

it("lists every open pool instead of silently cutting the list", async () => {
  transport.get.mockImplementation((path: string) => {
    if (path === "/api/v1/me/delegations") return Promise.resolve({ data: { items: [] } });
    return Promise.resolve({
      data: Array.from({ length: 9 }, (_, index) => ({
        pool_id: `pool-${index}`,
        title: `Pool ${index}`,
        status: "OPEN",
      })),
    });
  });
  showManual();

  expect(await screen.findByRole("checkbox", { name: "Pool 8" })).toBeInTheDocument();
  const poolChoices = within(screen.getByRole("group", { name: "Pools this delegation may use" }));
  expect(poolChoices.getAllByRole("checkbox")).toHaveLength(9);
});

it("shows a real error and a retry when the open pools cannot be loaded", async () => {
  let poolsFail = true;
  transport.get.mockImplementation((path: string) => {
    if (path === "/api/v1/me/delegations") return Promise.resolve({ data: { items: [] } });
    if (poolsFail) {
      return Promise.resolve({ error: { error: { code: "INTERNAL_ERROR", message: "Pools are down." } } });
    }
    return Promise.resolve({ data: [{ pool_id: "pool-one", title: "Demo pool", status: "OPEN" }] });
  });
  showManual();

  expect(await screen.findByText(/The open pools could not be loaded/)).toBeInTheDocument();
  expect(screen.queryByText("No open pools right now.")).not.toBeInTheDocument();

  poolsFail = false;
  fireEvent.click(screen.getByRole("button", { name: "Reload pools" }));

  expect(await screen.findByRole("checkbox", { name: "Demo pool" })).toBeInTheDocument();
});

it("revokes a delegation after a confirmation", async () => {
  transport.get.mockResolvedValue({ data: { items: [{
    id: "44444444-4444-4444-8444-444444444444",
    scope: { pool_ids: ["11111111-1111-4111-8111-111111111111"], category: null },
    max_cap_cents: 50000,
    expires_at: "2026-12-01T00:00:00Z",
    revoked_at: null,
  }] } });
  transport.delete.mockResolvedValue({ data: { items: [] } });
  showManual();

  fireEvent.click(await screen.findByRole("button", { name: "Revoke" }));
  expect(transport.delete).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", {name: "Confirm revoke delegation"}));
  await waitFor(() => expect(transport.delete).toHaveBeenCalledWith(
    "/api/v1/me/delegations/{delegation_id}",
    { params: { path: { delegation_id: "44444444-4444-4444-8444-444444444444" } } },
  ));
});

it("refuses to create a delegation with no pool selected", async () => {
  transport.get.mockImplementation((path: string) => {
    if (path === "/api/v1/pools") {
      return Promise.resolve({ data: [{ pool_id: "11111111-1111-4111-8111-111111111111", title: "Demo pool", status: "OPEN" }] });
    }
    return Promise.resolve({ data: { items: [] } });
  });
  showManual();

  const create = await screen.findByRole("button", {name: "Create delegation"});
  await waitFor(() => expect(create).toBeEnabled());
  fireEvent.click(create);
  expect(await screen.findByText(/Pick at least one pool/)).toBeInTheDocument();
  expect(transport.post).not.toHaveBeenCalled();
});

it("refuses scientific notation for a delegation's USD cap", async () => {
  transport.get.mockImplementation(async (path: string) => ({data: path === "/api/v1/pools" ? [{pool_id: "pool-one", title: "Test pool"}] : {items: []}}));
  showManual();
  fireEvent.click(await screen.findByRole("checkbox", {name: "Test pool"}));
  fireEvent.change(screen.getByLabelText("Maximum per entry (USD)"), {target: {value: "1e3"}});
  fireEvent.click(screen.getByRole("button", {name: "Create delegation"}));
  expect(transport.post).not.toHaveBeenCalled();
  expect(screen.getByRole("alert")).toHaveTextContent("VALIDATION_ERROR");
});

it("requires an explicit ratification before any delegation token is requested", async () => {
  transport.get.mockImplementation(async (path: string) => ({data: path === "/api/v1/pools" ? [{pool_id: "pool-one", title: "Test pool"}] : {items: []}}));
  showManual();

  fireEvent.click(await screen.findByRole("checkbox", {name: "Test pool"}));
  fireEvent.click(screen.getByRole("button", {name: "Create delegation"}));

  expect(await screen.findByRole("alert")).toHaveTextContent(/ratify the mandate/);
  expect(transport.post).not.toHaveBeenCalled();
  expect(screen.getByRole("button", {name: "Propose with AI"})).toBeInTheDocument();
});

it("renders the mandate for reading and hashes the canonical mandate fields with the token", async () => {
  const pool = { pool_id: "11111111-1111-4111-8111-111111111111", title: "Demo monitor pool" };
  transport.get.mockImplementation((path: string) => {
    if (path === "/api/v1/me/delegations") return Promise.resolve({ data: { items: [] } });
    if (path === "/api/v1/pools") return Promise.resolve({ data: [{ ...pool, status: "OPEN" }] });
    return Promise.resolve({ data: {} });
  });
  transport.post.mockResolvedValue({ data: { token: "fpd_abc_secret", id: "33333333-3333-4333-8333-333333333333" } });
  showManual();

  fireEvent.click(await screen.findByRole("checkbox", { name: /Demo monitor pool/ }));
  fireEvent.change(screen.getByLabelText("Expires (UTC)"), { target: { value: "2026-12-01T00:00" } });
  fireEvent.click(screen.getByRole("button", { name: "Add condition" }));
  fireEvent.change(screen.getByLabelText("Condition 1 amount (USD)"), { target: { value: "520" } });

  const rendered = screen.getByTestId("mandate-text").textContent ?? "";
  expect(rendered).toContain("If the price is above USD 520");
  expect(rendered).toContain("This mandate approves no payment.");

  fireEvent.click(screen.getByRole("checkbox", { name: /I approve this mandate/ }));
  fireEvent.click(screen.getByRole("button", { name: "Create delegation" }));

  // The canonical payload: sorted keys, compact JSON, the UTC millisecond expiry and
  // sorted lowercase pool ids. This is what the server recomputes and hashes.
  const canonical = JSON.stringify({
    category: null,
    conditions: [{ action: "REASK", params: { amount: "520" }, predicate: "PRICE_ABOVE" }],
    expires_at: "2026-12-01T00:00:00.000Z",
    max_cap_cents: 60000,
    pool_ids: [pool.pool_id],
  });
  const expectedHash = createHash("sha256").update(canonical).digest("hex");
  await waitFor(() => expect(transport.post).toHaveBeenCalledWith("/api/v1/me/delegations", {
    body: expect.objectContaining({
      max_cap_cents: 60000,
      expires_at: "2026-12-01T00:00:00.000Z",
      scope: expect.objectContaining({
        pool_ids: [pool.pool_id],
        mandate_version: "1",
        ratification_sha256: expectedHash,
        conditions: [{ predicate: "PRICE_ABOVE", params: { amount: "520" }, action: "REASK" }],
      }),
    }),
  }));
  expect(await screen.findByText("Copy this token now. It is shown once.")).toBeInTheDocument();
  expect(screen.getByText("fpd_abc_secret")).toBeInTheDocument();
});

it("updates the sidebar's connection state only after the server confirms revocation", async () => {
  setAccount({display_name: "Buyer", role: "buyer", paypal_linked: true});
  transport.get.mockResolvedValue({data: {paypal_linked: true}});
  transport.delete.mockResolvedValue({data: {paypal_linked: false}});
  render(<MemoryRouter future={{v7_startTransition: true, v7_relativeSplatPath: true}}><AreaLayout workspace="Buyer workspace" tabs={[]}><PayPalSettingsPage /></AreaLayout></MemoryRouter>);
  const rail = screen.getByRole("complementary", {name: "Workspace sidebar"});
  expect(within(rail).getByText("PayPal account linked")).toBeInTheDocument();
  fireEvent.click(await screen.findByRole("button", {name: "Revoke the link"}));
  expect(within(rail).getByText("PayPal account linked")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", {name: "Confirm revoke link"}));
  expect(await within(rail).findByText("No PayPal account linked yet")).toBeInTheDocument();
});


it("identifies named connections by public prefix and last use", async () => {
  transport.get.mockImplementation(async (path: string) => ({data: path === '/api/v1/pools' ? [] : {items: [{id: 'connected', name: 'Research assistant', key_prefix: '1234abcd', last_used_at: '2026-11-12T10:00:00Z', scope: {pool_ids: []}, max_cap_cents: 50000, expires_at: '2099-01-01T00:00:00Z', revoked_at: null}]}}));
  showManual();
  expect(await screen.findByText('Research assistant')).toBeInTheDocument();
  expect(screen.getByText('1234abcd')).toBeInTheDocument();
  expect(screen.getByText('Active')).toBeInTheDocument();
  expect(screen.getByText(/Last used:/)).not.toHaveTextContent('Never');
  fireEvent.click(screen.getByRole('button', {name: 'Connect an agent'}));
  expect(screen.getByLabelText('MCP server URL')).toHaveValue('http://localhost:8000/mcp');
});

it.each(['manual', 'outage'])("keeps the editable manual mandate when AI returns %s", async (source) => {
  transport.get.mockImplementation(async (path: string) => ({data: path === '/api/v1/pools' ? [{pool_id: 'pool-one', title: 'Monitor pool'}] : {items: []}}));
  transport.post.mockImplementation(async () => {if(source === 'outage') throw new Error('offline'); return {data: {source: 'manual', pool_ids: ['pool-one'], conditions: [], max_cap_cents: 60000}};});
  showManual();
  fireEvent.click(await screen.findByRole('checkbox', {name: 'Monitor pool'}));
  fireEvent.change(screen.getByLabelText('Describe your mandate'), {target: {value: 'Find a monitor under $600'}});
  fireEvent.click(screen.getByRole('button', {name: 'Propose with AI'}));
  expect(await screen.findByText(/Write or edit the mandate below/)).toBeInTheDocument();
  expect(screen.getByLabelText('Maximum per entry (USD)')).toHaveValue('600');
  expect(screen.getByRole('checkbox', {name: /I approve this mandate/})).not.toBeChecked();
});

it("loads an AI proposal into editable fields and requires ratification of the new cap", async () => {
  const id = "11111111-1111-4111-8111-111111111111";
  transport.get.mockImplementation(async (path: string) => ({data: path === "/api/v1/pools" ? [{pool_id: id, title: "Monitor pool"}] : {items: []}}));
  transport.post.mockImplementation(async (path: string) => ({data: path === "/api/v1/me/mandate-proposal" ? {
    source: "ai", pool_ids: [id], category: null, max_cap_cents: 52000, expires_at: "2099-01-01T23:59:59Z",
    conditions: [{predicate: "PRICE_ABOVE", params: {amount: "500.00"}, action: "REASK"}],
    reserved: ["payment_approval"], ambiguities: [], clarifying_question: null,
  } : {token: "test-only-token"}}));
  showManual();
  fireEvent.click(await screen.findByRole("checkbox", {name: "Monitor pool"}));
  fireEvent.change(screen.getByLabelText("Connection name"), {target: {value: "Research assistant"}});
  fireEvent.click(screen.getByRole("checkbox", {name: /I approve this mandate/}));
  fireEvent.change(screen.getByLabelText("Describe your mandate"), {target: {value: "Cap at $520, ask above $500"}});
  fireEvent.click(screen.getByRole("button", {name: "Propose with AI"}));
  await screen.findByText(/AI proposed the mandate below/);
  fireEvent.click(screen.getByRole("button", {name: "Edit limits and pools"}));
  expect(screen.getByLabelText("Condition 1 amount (USD)")).toHaveValue("500.00");
  expect(screen.getByRole("checkbox", {name: /I approve this mandate/})).not.toBeChecked();
  fireEvent.change(screen.getByLabelText("Maximum per entry (USD)"), {target: {value: "510"}});
  fireEvent.click(screen.getByRole("checkbox", {name: /I approve this mandate/}));
  fireEvent.click(screen.getByRole("button", {name: "Create delegation"}));
  await waitFor(() => expect(transport.post).toHaveBeenCalledWith("/api/v1/me/delegations", {body: expect.objectContaining({name: "Research assistant", max_cap_cents: 51000, scope: expect.objectContaining({pool_ids: [id], category: null})})}));
});
