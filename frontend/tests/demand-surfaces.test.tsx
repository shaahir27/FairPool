import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
const transport = vi.hoisted(() => ({get: vi.fn(), post: vi.fn(), delete: vi.fn()}));
vi.mock("../src/shared/api/client", () => ({api: {GET: transport.get, POST: transport.post, DELETE: transport.delete}, API_BASE_URL: "http://localhost:8000"}));
import { DiscoverPage } from "../src/buyer/discover/DiscoverPage";
import { MyPoolsPage } from "../src/buyer/my-pools/MyPoolsPage";
import { OpsPage } from "../src/ops";
import { NotificationInbox, readClient } from "../src/shared";

const cluster = {cluster_key: "abc123", title: "Ceramic kettle", product_key: "ceramic-kettle", condition: "NEW", variant: "white", bundle_contents: ["kettle", "base"], regions: ["NY"], interested: 4, threshold: 5, status: "COLLECTING"};
let clusters: unknown[]; let interests: unknown[]; let proposals: unknown[];
beforeEach(() => {
  clusters = [cluster]; interests = []; proposals = [];
  transport.get.mockReset().mockImplementation(async (path: string) => ({data: path === "/api/v1/demand-clusters" ? clusters : path === "/api/v1/me/demand-signals" ? interests : path === "/api/v1/me/entries" ? {items: []} : path === "/api/v1/admin/demand-proposals" ? proposals : path === "/api/v1/me/notifications" ? {items: [], unread: 0} : []}));
  transport.post.mockReset().mockImplementation(async (path: string) => ({data: path === "/api/v1/intake/messages" ? {status: "NO_MATCH", session_id: "intake-one", clarifying_question: "No matching pool."} : {signal_id: "mine"}}));
  transport.delete.mockReset().mockImplementation(async () => {interests = []; return {data: null};});
});
function show(page: React.ReactNode, path = "/discover") { return render(<MemoryRouter initialEntries={[path]}>{page}</MemoryRouter>); }

it("shows only aggregate forming demand and records nothing on decline", async () => {
  show(<DiscoverPage />);
  expect(await screen.findByText("Ceramic kettle")).toBeInTheDocument();
  expect(screen.getByText("4 of 5 interested")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", {name: "Notify me"}));
  fireEvent.click(screen.getByRole("button", {name: "Not now"}));
  expect(transport.post).not.toHaveBeenCalled();
});
it("saves only confirmed product fields and region with explicit consent", async () => {
  show(<DiscoverPage />);
  fireEvent.click(await screen.findByRole("button", {name: "Notify me"}));
  const form = screen.getByRole("form", {name: "Demand notification consent"});
  fireEvent.change(within(form).getByLabelText("Delivery region (US state code)"), {target: {value: "NY"}});
  expect(within(form).getByRole("button", {name: "Save interest"})).toBeDisabled();
  fireEvent.click(within(form).getByRole("checkbox", {name: /I confirm these product fields/}));
  fireEvent.click(within(form).getByRole("button", {name: "Save interest"}));
  await waitFor(() => expect(transport.post).toHaveBeenCalledWith("/api/v1/me/demand-signals", {body: {product_key: "ceramic-kettle", condition: "NEW", variant: "white", bundle_contents: ["kettle", "base"], region: "NY", source: "discover"}}));
  expect(await screen.findByText(/Interest saved/)).toBeInTheDocument();
});
it("offers intake consent after no match without copying the private prompt into a signal", async () => {
  show(<DiscoverPage />);
  fireEvent.change(screen.getByLabelText("What are you looking for and what is your max price?"), {target: {value: "A kettle under $80 for my private office"}});
  fireEvent.click(screen.getByRole("button", {name: "Find matches"}));
  fireEvent.click(await screen.findByRole("button", {name: "Notify me when a pool forms"}));
  expect(screen.getByLabelText("Product key")).toHaveValue("");
  fireEvent.click(screen.getByRole("button", {name: "Not now"}));
  expect(transport.post.mock.calls.map(([path]) => path)).toEqual(["/api/v1/intake/messages"]);
});
it("renders forming empty and retry states", async () => {
  clusters = []; const view = show(<DiscoverPage />);
  expect(await screen.findByText("No forming demand yet.")).toBeInTheDocument(); view.unmount(); readClient.clear();
  transport.get.mockImplementation(async () => ({error: {error: {code: "UNAVAILABLE", message: "Try again"}}}));
  show(<DiscoverPage />);
  expect(await screen.findByText(/Forming demand could not be loaded/)).toBeInTheDocument();
});
it("lists and cancels the buyer's interests", async () => {
  interests = [{signal_id: "mine", cluster_key: "abc123", title: "Ceramic kettle", status: "COLLECTING", pool_id: null, interested: 4, threshold: 5, expires_at: "2099-01-01T00:00:00Z"}];
  show(<MyPoolsPage />, "/my-pools");
  expect(await screen.findByRole("heading", {name: "Interests"})).toBeInTheDocument();
  fireEvent.click(await screen.findByRole("button", {name: "Cancel interest"}));
  await waitFor(() => expect(transport.delete).toHaveBeenCalledWith("/api/v1/me/demand-signals/{signal_id}", {params: {path: {signal_id: "mine"}}}));
  expect(await screen.findByText("No active interests.")).toBeInTheDocument();
});
it.each(["publish", "reject"])("lets an operator %s a proposed draft", async (action) => {
  proposals = [{...cluster, pool_id: "draft-one", status: "PROPOSED", proposed_at: "2026-11-12T09:00:00Z"}];
  show(<OpsPage />, "/ops/demand");
  fireEvent.click(await screen.findByRole("button", {name: action === "publish" ? "Publish pool" : "Reject proposal"}));
  await waitFor(() => expect(transport.post).toHaveBeenCalledWith(`/api/v1/admin/demand-proposals/{cluster_key}/${action}`, {params: {path: {cluster_key: "abc123"}}}));
  expect(await screen.findByText(action === "publish" ? /Pool published/ : /Proposal rejected/)).toBeInTheDocument();
});
it("keeps failed publication actionable", async () => {
  proposals = [{...cluster, pool_id: "draft-one", status: "PROPOSED"}];
  transport.post.mockRejectedValue(new Error("offline"));
  show(<OpsPage />, "/ops/demand");
  fireEvent.click(await screen.findByRole("button", {name: "Publish pool"}));
  expect(await screen.findByRole("alert")).toHaveTextContent("could not be saved");
  expect(screen.getByRole("button", {name: "Publish pool"})).toBeEnabled();
});
it("describes demand notifications without exposing their JSON payload", async () => {
  transport.get.mockResolvedValue({data: {items: [{id: "proposed", kind: "demand.pool_proposed", payload: {title: "Ceramic kettle", cluster_key: "private-key"}, created_at: "2026-11-12T09:00:00Z", read_at: "2026-11-12T10:00:00Z"}, {id: "open", kind: "demand.pool_open", payload: {title: "Ceramic kettle"}, created_at: "2026-11-12T09:00:00Z", read_at: "2026-11-12T10:00:00Z"}], unread: 0}});
  show(<NotificationInbox />);
  fireEvent.click(screen.getByRole("button", {name: /Notifications/}));
  expect(await screen.findByText(/A pool for Ceramic kettle was proposed/)).toBeInTheDocument();
  expect(screen.getByText(/A pool for Ceramic kettle was published/)).toBeInTheDocument();
  expect(screen.queryByText(/private-key/)).toBeNull();
});

it("shows empty interests without implying that a pool was joined", async () => {
  show(<MyPoolsPage />, "/my-pools");
  expect(await screen.findByText("No active interests.")).toBeInTheDocument();
  expect(screen.getByText(/An interest is not an entry/)).toBeInTheDocument();
});
it("offers a retry when the interests read fails", async () => {
  transport.get.mockImplementation(async (path: string) => path === "/api/v1/me/demand-signals" ? {error: {error: {code: "UNAVAILABLE", message: "Offline"}}} : {data: {items: []}});
  show(<MyPoolsPage />, "/my-pools");
  expect(await screen.findByRole("alert")).toHaveTextContent("Your interests could not be loaded");
  expect(screen.getByRole("button", {name: "Retry interests"})).toBeEnabled();
  expect(screen.queryByText("No active interests.")).toBeNull();
});
it("shows an empty operator queue", async () => {
  show(<OpsPage />, "/ops/demand");
  expect(await screen.findByText("No demand proposals yet.")).toBeInTheDocument();
  expect(screen.queryByRole("button", {name: "Publish pool"})).toBeNull();
});
it("offers a retry when the proposal queue cannot be read", async () => {
  transport.get.mockResolvedValue({error: {error: {code: "UNAVAILABLE", message: "Offline"}}});
  show(<OpsPage />, "/ops/demand");
  expect(await screen.findByRole("alert")).toHaveTextContent("Demand proposals could not be loaded");
  expect(screen.getByRole("button", {name: "Retry proposals"})).toBeEnabled();
});
