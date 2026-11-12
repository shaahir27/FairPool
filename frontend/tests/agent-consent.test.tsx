import { createHash } from "node:crypto";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const transport = vi.hoisted(() => ({get: vi.fn(), post: vi.fn()}));
vi.mock("../src/shared/api/client", () => ({api: {GET: transport.get, POST: transport.post}, API_BASE_URL: "http://localhost:8000"}));
import { AgentAuthorizePage } from "../src/buyer/AgentAuthorizePage";
import { setCsrfToken, workspaceRole } from "../src/shared";

const request = {response_type: "code", client_id: "fpc_test", redirect_uri: "http://127.0.0.1:9000/callback", state: "preserve-me", code_challenge: "challenge", code_challenge_method: "S256"};
const fetcher = vi.fn();
beforeEach(() => {
  setCsrfToken("test-csrf");
  transport.get.mockReset().mockImplementation(async (path: string) => ({data: path === "/api/v1/pools" ? [{pool_id: "11111111-1111-4111-8111-111111111111", title: "Monitor pool"}] : {items: []}}));
  transport.post.mockReset();
  fetcher.mockReset().mockImplementation(async (_url: string, init?: RequestInit) => new Response(JSON.stringify(init?.method === "POST" ? {redirect_to: "http://localhost:3000/#returned"} : {client_name: "My assistant", redirect_uri: request.redirect_uri}), {status: 200}));
  vi.stubGlobal("fetch", fetcher);
});
afterEach(() => vi.unstubAllGlobals());
function show() { return render(<MemoryRouter initialEntries={[`/agents/authorize?${new URLSearchParams(request)}`]}><AgentAuthorizePage /></MemoryRouter>); }

it("preserves the buyer login return path for OAuth", () => expect(workspaceRole("/agents/authorize?state=x")).toBe("buyer"));
it("denies without a mandate and sends only the validated authorization fields with CSRF", async () => {
  show();
  expect(await screen.findByText("My assistant")).toBeInTheDocument();
  expect(screen.getByText(request.redirect_uri)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", {name: "Deny"}));
  await waitFor(() => expect(fetcher).toHaveBeenCalledWith(expect.stringContaining("/oauth/authorize/decision"), expect.objectContaining({credentials: "include", headers: {"Content-Type": "application/json", "X-CSRF-Token": "test-csrf"}, body: JSON.stringify({...request, approved: false})})));
  expect(transport.post).not.toHaveBeenCalled();
});
it("approves only after ratification and hashes the chosen mandate, without minting a manual token", async () => {
  show();
  fireEvent.click(await screen.findByRole("button", {name: "Choose fields myself"}));
  fireEvent.click(await screen.findByRole("checkbox", {name: "Monitor pool"}));
  fireEvent.click(screen.getByRole("button", {name: "Approve connection"}));
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(0);
  fireEvent.click(screen.getByRole("checkbox", {name: /I approve this mandate/}));
  fireEvent.click(screen.getByRole("button", {name: "Approve connection"}));
  await waitFor(() => expect(fetcher.mock.calls.some(([, init]) => init?.method === "POST")).toBe(true));
  const sent = JSON.parse(fetcher.mock.calls.find(([, init]) => init?.method === "POST")![1].body);
  expect(sent.approved).toBe(true);
  expect(sent).not.toHaveProperty("client_name");
  const canonical = JSON.stringify({category: null, conditions: [], expires_at: sent.expires_at, max_cap_cents: 60000, pool_ids: ["11111111-1111-4111-8111-111111111111"]});
  expect(sent.scope.ratification_sha256).toBe(createHash("sha256").update(canonical).digest("hex"));
  expect(transport.post).not.toHaveBeenCalled();
});
it("shows a retry and no approval controls if the request cannot be validated", async () => {
  fetcher.mockResolvedValue(new Response("{}", {status: 400})); show();
  expect(await screen.findByRole("alert")).toHaveTextContent("could not be verified");
  expect(screen.queryByRole("button", {name: "Approve connection"})).toBeNull();
  expect(screen.getByRole("button", {name: "Try again"})).toBeEnabled();
});
