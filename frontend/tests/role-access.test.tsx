import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";

const transport = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("../src/shared/api/client", () => ({
  api: { GET: transport.get, POST: transport.post }, API_BASE_URL: "http://localhost:8000",
}));
import { AppRoutes } from "../src/App";
import { resetSessionCache } from "../src/shared";

let role = "admin";
beforeEach(() => {
  resetSessionCache();
  sessionStorage.clear();
  role = "admin";
  transport.get.mockReset().mockImplementation((path: string) => Promise.resolve({
    data: path === "/api/v1/me" ? { display_name: "Test account", role, paypal_linked: false }
      : path === "/api/v1/admin/alerts" ? { alerts: [] }
      : path === "/api/v1/admin/webhooks/dead-letter" ? { events: [] } : [],
    response: { ok: true, status: 200 },
  }));
  transport.post.mockReset().mockResolvedValue({ data: { csrf_token: "test-csrf" } });
});

function visit(path: string, from?: string) {
  render(<MemoryRouter initialEntries={[{ pathname: path.split("?")[0] ?? "/", search: path.includes("?") ? `?${path.split("?")[1]}` : "", state: from ? { from } : undefined }]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><AppRoutes /></MemoryRouter>);
}

async function signIn() {
  fireEvent.change(await screen.findByLabelText("Email"), { target: { value: "person@example.test" } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: "test-password" } });
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
}

it.each([
  ["admin", "/login", "Ops console"],
  ["merchant", "/login", "Demand Board"],
  ["buyer", "/login?role=merchant", "Open pools"],
])("routes %s by its server role after login", async (accountRole, path, heading) => {
  role = accountRole;
  visit(path);
  await signIn();
  expect(await screen.findByRole("heading", { level: 1, name: heading })).toBeInTheDocument();
  expect(transport.get).toHaveBeenCalledWith("/api/v1/me");
});

it.each([
  ["admin", "/discover", "Ops console"],
  ["admin", "/orders/someone-elses-order", "Ops console"],
  ["buyer", "/ops", "Open pools"],
  ["merchant", "/ops", "Demand Board"],
  ["buyer", "/merchant/bids", "Open pools"],
  ["merchant", "/orders", "Demand Board"],
])("keeps %s out of %s", async (accountRole, path, heading) => {
  role = accountRole;
  visit(path);
  expect(await screen.findByRole("heading", { level: 1, name: heading })).toBeInTheDocument();
  if (accountRole !== "admin") expect(transport.get.mock.calls.some(([url]) => url.startsWith("/api/v1/admin/"))).toBe(false);
  if (accountRole === "admin") expect(transport.get.mock.calls.some(([url]) => url.startsWith("/api/v1/orders/"))).toBe(false);
});

it("keeps a merchant's intended destination within its workspace", async () => {
  role = "merchant";
  visit("/login", "/merchant/bids");
  await signIn();
  expect(await screen.findByRole("heading", { name: "Active Bids" })).toBeInTheDocument();
});

it("discards a previous user's buyer destination when an admin signs in", async () => {
  visit("/login", "/orders");
  await signIn();
  expect(await screen.findByRole("heading", { name: "Ops console" })).toBeInTheDocument();
});

it("does not render a workspace without a verified role", async () => {
  role = "";
  visit("/ops");
  expect(await screen.findByRole("alert")).toHaveTextContent("Account access unavailable");
  expect(transport.get.mock.calls.some(([url]) => url.startsWith("/api/v1/admin/"))).toBe(false);
});

it("stays on login when the account lookup fails after password verification", async () => {
  transport.get.mockResolvedValue({ error: { error: { code: "REQUEST_FAILED", message: "Account could not be loaded." } }, response: { ok: false, status: 503 } });
  visit("/login");
  await signIn();
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Account could not be loaded."));
  expect(screen.getByRole("heading", { name: "Sign in" })).toBeInTheDocument();
});
