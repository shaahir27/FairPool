import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const transport = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), delete: vi.fn() }));
vi.mock("../src/shared/api/client", () => ({
  api: { GET: transport.get, POST: transport.post, DELETE: transport.delete },
  API_BASE_URL: "http://localhost:8000",
}));

import { AgentSettingsPage, PayPalSettingsPage } from "../src/buyer/pages";

beforeEach(() => {
  transport.get.mockReset();
  transport.post.mockReset();
  transport.delete.mockReset();
  vi.restoreAllMocks();
});

afterEach(() => {
  vi.useRealTimers();
});

it("shows the PayPal link state and revokes it after a confirmation", async () => {
  transport.get.mockResolvedValue({ data: { paypal_linked: true } });
  transport.delete.mockResolvedValue({ data: { paypal_linked: false } });
  vi.spyOn(window, "confirm").mockReturnValue(true);
  render(<MemoryRouter><PayPalSettingsPage /></MemoryRouter>);

  expect(await screen.findByText("A PayPal account is linked.")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Revoke the link" }));

  await waitFor(() => expect(transport.delete).toHaveBeenCalledWith("/api/v1/paypal/link"));
  expect(await screen.findByText("No PayPal account is linked yet.")).toBeInTheDocument();
});

it("revokes nothing when the confirmation is cancelled", async () => {
  transport.get.mockResolvedValue({ data: { paypal_linked: true } });
  vi.spyOn(window, "confirm").mockReturnValue(false);
  render(<MemoryRouter><PayPalSettingsPage /></MemoryRouter>);

  fireEvent.click(await screen.findByRole("button", { name: "Revoke the link" }));

  expect(transport.delete).not.toHaveBeenCalled();
  expect(screen.getByText("A PayPal account is linked.")).toBeInTheDocument();
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
  render(<MemoryRouter><AgentSettingsPage /></MemoryRouter>);

  const checkbox = await screen.findByRole("checkbox", { name: /Demo monitor pool/ });
  fireEvent.click(checkbox);
  fireEvent.click(screen.getByRole("button", { name: "Create delegation" }));

  await waitFor(() => expect(transport.post).toHaveBeenCalledWith("/api/v1/me/delegations", {
    body: expect.objectContaining({ max_cap_cents: 60000, scope: expect.objectContaining({ pool_ids: [pool.pool_id] }) }),
  }));
  expect(await screen.findByText("Copy this token now. It is shown once.")).toBeInTheDocument();
  expect(screen.getByText("fpd_abc_secret")).toBeInTheDocument();
  const list = screen.getByRole("heading", { name: "Your delegations" }).parentElement!;
  expect(within(list).getByText(/1 pool/)).toBeInTheDocument();
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
  render(<MemoryRouter><AgentSettingsPage /></MemoryRouter>);

  expect(await screen.findByRole("checkbox", { name: "Pool 8" })).toBeInTheDocument();
  expect(screen.getAllByRole("checkbox")).toHaveLength(9);
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
  render(<MemoryRouter><AgentSettingsPage /></MemoryRouter>);

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
  vi.spyOn(window, "confirm").mockReturnValue(true);
  render(<MemoryRouter><AgentSettingsPage /></MemoryRouter>);

  fireEvent.click(await screen.findByRole("button", { name: "Revoke" }));
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
  render(<MemoryRouter><AgentSettingsPage /></MemoryRouter>);

  fireEvent.click(await screen.findByRole("button", { name: "Create delegation" }));
  expect(await screen.findByText(/Pick at least one pool/)).toBeInTheDocument();
  expect(transport.post).not.toHaveBeenCalled();
});
