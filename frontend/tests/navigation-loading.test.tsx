import { act, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
const transport = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock("../src/shared/api/client", () => ({api: {GET: transport.get}, API_BASE_URL: "http://localhost:8000"}));
import { RequireAuth, resetSessionCache } from "../src/shared";

beforeEach(() => { resetSessionCache(); transport.get.mockReset(); });

it.each([
  ["buyer", "/discover", "/api/v1/pools"],
  ["merchant", "/merchant/demand", "/api/v1/merchant/lots"],
  ["admin", "/ops", "/api/v1/admin/alerts"],
] as const)("preloads %s data at its permitted authentication boundary", async (role, route, endpoint) => {
  let finish!: (value: unknown) => void;
  transport.get.mockImplementation((path: string) => path === "/api/v1/me"
    ? new Promise((resolve) => {finish = resolve;}) : Promise.resolve({data: []}));
  render(<MemoryRouter initialEntries={[route]} future={{v7_startTransition: true, v7_relativeSplatPath: true}}>
    <RequireAuth role={role}><h1>Private workspace</h1></RequireAuth>
  </MemoryRouter>);
  expect(screen.queryByText("Private workspace")).toBeNull();
  if (role === "buyer") await waitFor(() => expect(transport.get.mock.calls.some(([path]) => path === endpoint)).toBe(true));
  else expect(transport.get.mock.calls.some(([path]) => path === endpoint)).toBe(false);
  await act(async () => {finish({data: {display_name: "Demo", role, paypal_linked: false}, response: new Response(null, {status: 200})});});
  expect(await screen.findByText("Private workspace")).toBeInTheDocument();
  expect(transport.get.mock.calls.some(([path]) => path === endpoint)).toBe(true);
});
