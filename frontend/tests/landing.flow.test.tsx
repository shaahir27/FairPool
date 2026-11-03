import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";

const transport = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("../src/shared/api/client", () => ({
  api: { GET: transport.get, POST: transport.post }, API_BASE_URL: "http://localhost:8000",
}));
import { AppRoutes } from "../src/App";
import { resetSessionCache } from "../src/shared";

beforeEach(() => {
  vi.stubGlobal("matchMedia", vi.fn((query: string) => ({ matches: query.includes("prefers-reduced-motion"), media: query })));
  vi.stubGlobal("IntersectionObserver", class {
    observe() {}
    disconnect() {}
  });
  resetSessionCache();
  transport.get.mockReset().mockImplementation((path: string) => Promise.resolve(
    path === "/api/v1/me" ? { data: {}, response: { ok: true, status: 200 } } : { data: [] },
  ));
  transport.post.mockReset().mockResolvedValue({ data: { csrf_token: "test-csrf" } });
});

function visit(path = "/") {
  render(<MemoryRouter initialEntries={[path]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><AppRoutes /></MemoryRouter>);
}

it("shows the landing publicly without asking for a session", async () => {
  visit();
  expect(await screen.findByRole("heading", { level: 1, name: /Buy together/ })).toBeInTheDocument();
  expect(transport.get).not.toHaveBeenCalled();
});

it.each([
  ["Join a pool", "Open pools"],
  ["Open merchant area", "Demand Board"],
])("takes %s through login to %s", async (action, destination) => {
  visit();
  const hero = await screen.findByRole("region", { name: /Buy together/ });
  fireEvent.click(within(hero).getByRole("link", { name: action }));
  expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Back to landing page" })).toHaveAttribute("href", "/");
  fireEvent.change(screen.getByLabelText("Email"), { target: { value: "person@example.com" } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: "example-password" } });
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
  expect(await screen.findByRole("heading", { name: destination })).toBeInTheDocument();
  expect(transport.post).toHaveBeenCalledWith("/api/v1/auth/login", expect.any(Object));
});

it.each(["/login", "/login?role=merchant"])("returns from %s to landing", async (path) => {
  visit(path);
  fireEvent.click(await screen.findByRole("link", { name: "Back to landing page" }));
  expect(await screen.findByRole("heading", { level: 1, name: /Buy together/ })).toBeInTheDocument();
});

it("sends a signed-out merchant deep link back to the same workspace after login", async () => {
  transport.get.mockResolvedValueOnce({ response: { status: 401 } });
  visit("/merchant/bids");
  expect(await screen.findByText("Sign in to your merchant workspace.")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Email"), { target: { value: "merchant@example.com" } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: "example-password" } });
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
  expect(await screen.findByRole("heading", { name: "Active Bids" })).toBeInTheDocument();
});

it("keeps all five walkthrough descriptions readable without playback controls", async () => {
  visit();
  const how = await screen.findByRole("region", { name: "How a pool works" });
  const steps = within(how).getByRole("list");
  expect(within(steps).getAllByRole("listitem")).toHaveLength(5);
  expect(within(steps).getByRole("heading", { name: /Payment follows your consent/ })).toBeVisible();
  expect(within(steps).getByRole("heading", { name: /The order goes ahead only when enough people pay/ })).toBeVisible();
  expect(within(how).queryByRole("button")).not.toBeInTheDocument();
});
