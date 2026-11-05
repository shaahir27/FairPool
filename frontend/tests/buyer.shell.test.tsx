import { lazy, Suspense } from "react";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const transport = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("../src/shared/api/client", () => ({
  api: { GET: transport.get, POST: transport.post },
  API_BASE_URL: "http://localhost:8000",
}));

import { AppRoutes } from "../src/App";
import { AreaLayout, resetSessionCache, setAccount } from "../src/shared";

function me(data: Record<string, unknown>) {
  return Promise.resolve({ data, error: undefined, response: { ok: true, status: 200 } });
}

async function renderAt(path: string) {
  resetSessionCache();
  setAccount(null);
  const view = render(
    <MemoryRouter
      initialEntries={[path]}
      future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
    >
      <AppRoutes />
    </MemoryRouter>,
  );
  await screen.findByRole("heading", { level: 1, name: "Orders" });
  return view;
}

beforeEach(() => {
  sessionStorage.clear();
  transport.get.mockReset();
  transport.post.mockReset();
});

describe("merchant workspace navigation", () => {
  it("keeps merchant destinations separate from account settings in the shared rail", () => {
    render(<MemoryRouter initialEntries={["/merchant/bids"]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <AreaLayout workspace="Merchant workspace" tabs={[{to: "/merchant/demand", label: "Demand Board", end: false}, {to: "/merchant/bids", label: "Active Bids", end: false}]} utilityLinks={[{to: "/merchant/profile", label: "Profile"}]}><h1>Active Bids</h1></AreaLayout>
    </MemoryRouter>);
    expect(screen.getByText("Merchant workspace", {selector: "p.sidebar-hello-name"})).toBeInTheDocument();
    const mobile = screen.getByRole("navigation", {name: "Mobile merchant workspace navigation"});
    expect(within(mobile).getByRole("link", {name: "Active Bids"})).toHaveAttribute("aria-current", "page");
    expect(within(mobile).queryByText("Profile")).toBeNull();
  });
});

describe("the buyer workspace shell", () => {
  it("exposes shopping destinations separately from mobile account settings", () => {
    render(<MemoryRouter initialEntries={["/orders"]}>
      <AreaLayout workspace="Buyer workspace" tabs={[{ to: "/", label: "Discover and Join", end: true }, { to: "/my-pools", label: "My Pools", end: true }, { to: "/orders", label: "Orders", end: true }]} utilityLinks={[{ to: "/addresses", label: "Delivery addresses" }]}><h1>Orders</h1></AreaLayout>
    </MemoryRouter>);
    const shopping = screen.getByRole("navigation", { name: "Mobile shopping navigation" });
    expect(within(shopping).getByRole("link", { name: "Orders" })).toHaveAttribute("aria-current", "page");
    expect(within(shopping).getAllByRole("link")).toHaveLength(3);
    const settings = screen.getByRole("navigation", { name: "Mobile buyer navigation", hidden: true });
    expect(within(settings).getByText("Delivery addresses")).toBeInTheDocument();
    expect(within(settings).queryByText("Orders")).toBeNull();
  });
  it("keeps navigation visible while the next page downloads", async () => {
    let finish!: (value: { default: () => React.JSX.Element }) => void;
    const PendingPage = lazy(() => new Promise<{ default: () => React.JSX.Element }>((resolve) => { finish = resolve; }));
    render(<MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <Suspense fallback={<p>Loading app</p>}>
        <AreaLayout workspace="Buyer workspace" tabs={[{ to: "/", label: "Discover and Join", end: true }]}><PendingPage /></AreaLayout>
      </Suspense>
    </MemoryRouter>);
    expect(screen.getByRole("navigation", { name: "Buyer workspace tabs" })).toBeInTheDocument();
    expect(screen.getByRole("status", { name: "Loading workspace page" })).toBeInTheDocument();
    await act(async () => { finish({ default: () => <h1>Ready page</h1> }); });
    expect(await screen.findByRole("heading", { name: "Ready page" })).toBeInTheDocument();
    expect(screen.queryByRole("status", { name: "Loading workspace page" })).toBeNull();
  });

  it("greets the signed-in buyer with what the server actually said", async () => {
    transport.get.mockImplementation((path: string) =>
      path === "/api/v1/me"
        ? me({
            user_id: "u1",
            email: "priya@example.test",
            display_name: "Priya Raman",
            role: "buyer",
            paypal_linked: true,
            unread_notifications: 0,
          })
        : Promise.resolve({ data: undefined, error: {}, response: { ok: false, status: 404 } }),
    );
    await renderAt("/orders");

    expect(await screen.findByText("Hi, Priya")).toBeInTheDocument();
    expect(screen.getByText("PayPal account linked")).toBeInTheDocument();
    expect(screen.getByText("Priya Raman's account")).toBeInTheDocument();
  });

  it("states an unlinked PayPal account as a fact, without promising a link screen", async () => {
    transport.get.mockImplementation((path: string) =>
      path === "/api/v1/me"
        ? me({
            user_id: "u1",
            email: "new@example.test",
            display_name: "New Buyer",
            role: "buyer",
            paypal_linked: false,
            unread_notifications: 0,
          })
        : Promise.resolve({ data: undefined, error: {}, response: { ok: false, status: 404 } }),
    );
    await renderAt("/orders");

    expect(await screen.findByText("No PayPal account linked yet")).toBeInTheDocument();
    expect(screen.queryByText("PayPal account linked")).toBeNull();
  });

  it("signs out: the server ends the session and the browser forgets the token", async () => {
    transport.get.mockImplementation((path: string) =>
      path === "/api/v1/me"
        ? me({
            user_id: "u1",
            email: "priya@example.test",
            display_name: "Priya Raman",
            role: "buyer",
            paypal_linked: true,
            unread_notifications: 0,
          })
        : Promise.resolve({ data: undefined, error: {}, response: { ok: false, status: 404 } }),
    );
    transport.post.mockResolvedValue({
      data: {},
      error: undefined,
      response: { ok: true, status: 200 },
    });
    sessionStorage.setItem("fairpool.csrf", "a-token");
    await renderAt("/orders");

    // The rail and the mobile menu each carry the control; only one is ever visible,
    // so the test reads the rail's.
    const rail = document.querySelector(".account-sidebar") as HTMLElement;
    fireEvent.click(within(rail).getByRole("button", { name: "Sign out" }));
    await waitFor(() => expect(transport.post).toHaveBeenCalled());
    expect(transport.post.mock.calls[0]?.[0]).toBe("/api/v1/auth/logout");
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(sessionStorage.getItem("fairpool.csrf")).toBeNull();
  });

  it("says so when the sign-out call fails, and keeps the buyer where they were", async () => {
    transport.get.mockImplementation((path: string) =>
      path === "/api/v1/me"
        ? me({
            user_id: "u1",
            email: "priya@example.test",
            display_name: "Priya Raman",
            role: "buyer",
            paypal_linked: true,
            unread_notifications: 0,
          })
        : Promise.resolve({ data: undefined, error: {}, response: { ok: false, status: 404 } }),
    );
    transport.post.mockResolvedValue({
      data: undefined,
      error: { error: { code: "REQUEST_FAILED", message: "No answer." } },
      response: { ok: false, status: 503 },
    });
    await renderAt("/orders");

    // The rail and the mobile menu each carry the control; only one is ever visible,
    // so the test reads the rail's.
    const rail = document.querySelector(".account-sidebar") as HTMLElement;
    fireEvent.click(within(rail).getByRole("button", { name: "Sign out" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Still signed in");
    expect(screen.getByRole("heading", { level: 1, name: "Orders" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Sign in" })).toBeNull();
  });
});

it.each(["Buyer workspace", "Merchant workspace", "Ops console"])("keeps sign out reachable in both navigation layouts for %s", (workspace) => {
  render(<MemoryRouter future={{v7_startTransition: true, v7_relativeSplatPath: true}}><AreaLayout workspace={workspace} tabs={[]}><h1>Workspace content</h1></AreaLayout></MemoryRouter>);
  const rail = screen.getByRole("complementary", {name: "Workspace sidebar"});
  expect(within(rail).getByRole("button", {name: "Sign out"})).toBeInTheDocument();
  const summary = screen.getByText("Account", {selector: "summary span"});
  fireEvent.click(summary);
  const menu = summary.closest("details")!;
  expect(menu.open).toBe(true);
  expect(within(menu).getByRole("button", {name: "Sign out"})).toBeInTheDocument();
  fireEvent.pointerDown(screen.getByRole("heading", {name: "Workspace content"}));
  expect(menu.open).toBe(false);
  fireEvent.click(summary);
  fireEvent.keyDown(menu, {key: "Escape"});
  expect(menu.open).toBe(false);
  expect(summary.closest("summary")).toHaveFocus();
});
