import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
const transport = vi.hoisted(() => ({get: vi.fn(), post: vi.fn()}));
vi.mock("../src/shared/api/client", () => ({api: {GET: transport.get, POST: transport.post}, API_BASE_URL: "http://localhost:8000"}));
import { MyPoolsPage } from "../src/buyer/my-pools/MyPoolsPage";
import { resetBuyerPrefetch } from "../src/buyer/prefetch";

const pending = {entry_id: "entry-one", pool_id: "pool-one", pool_title: "Workstation pool", entry_status: "SUBMITTED", allocation: null, offer: null, product: {title: "27-inch monitor", variant: "Black", condition: "NEW", bundle_contents: ["Monitor", "Stand"]}};
const waiting = {...pending, entry_id: "entry-wait", pool_id: "pool-wait", product: {...pending.product, title: "Ceramic kettle"}, allocation: {status: "WAITLISTED", zone_id: "US-EAST", rank: 8, waitlist_position: 3, lot_id: "lot-one"}};
const offer = {...pending, entry_id: "entry-offer", pool_id: "pool-offer", product: {...pending.product, title: "Desk lamp"}, offer: {buyer_order_id: "order-one", status: "OFFERED", offer_expires_at: "2026-12-01T12:00:00Z"}};
function show() {
  return render(<MemoryRouter future={{v7_startTransition: true, v7_relativeSplatPath: true}}><Routes><Route path="/" element={<MyPoolsPage />} /><Route path="/offers/:id" element={<h1>Offer review destination</h1>} /><Route path="/orders/:id" element={<h1>Order destination</h1>} /><Route path="/pools/:id" element={<h1>Pool destination</h1>} /></Routes></MemoryRouter>);
}
beforeEach(() => {resetBuyerPrefetch(); transport.get.mockReset(); transport.post.mockReset();});
function entries(items: unknown[]) {transport.get.mockResolvedValue({data: {items}});}

it("opens on one current-pool list instead of stacked technical status sections", async () => {
  entries([pending, waiting, offer]); show();
  const feed = await screen.findByRole("list", {name: "Current pool entries"});
  expect(within(feed).getAllByRole("article")).toHaveLength(3);
  expect(screen.queryByRole("heading", {name: "Pending"})).toBeNull();
  expect(screen.queryByRole("heading", {name: "Waitlist"})).toBeNull();
  expect(screen.queryByRole("heading", {name: "Action required"})).toBeNull();
  expect(screen.getByRole("button", {name: "Current pools 3"})).toHaveAttribute("aria-pressed", "true");
});
it("puts a named offer first and takes review to the existing checkout route without a payment write", async () => {
  entries([pending, waiting, offer]); show();
  const feed = await screen.findByRole("list", {name: "Current pool entries"});
  expect(within(feed).getAllByRole("heading")[0]).toHaveTextContent("Desk lamp");
  expect(screen.getByText("Offer ready to review")).toBeInTheDocument();
  expect(screen.getByText(/Review by/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("link", {name: "Review offer"}));
  expect(await screen.findByRole("heading", {name: "Offer review destination"})).toBeInTheDocument();
  expect(transport.post).not.toHaveBeenCalled();
});
it("shows the server's waiting-list position without substituting allocation rank", async () => {
  entries([waiting]); show();
  expect(await screen.findByText("You're #3 on the waiting list.")).toBeInTheDocument();
  expect(screen.getByText("On the waiting list")).toBeInTheDocument();
});
it("does not invent a waiting-list position when it is unavailable", async () => {
  entries([{...waiting, allocation: {...waiting.allocation, waitlist_position: null}}]); show();
  expect(await screen.findByText("You're on the waiting list. Your position is not available yet.")).toBeInTheDocument();
  expect(screen.queryByText(/#8/)).toBeNull();
});
it("separates withdrawn and completed entries from current participation", async () => {
  entries([pending, {...pending, entry_id: "withdrawn", entry_status: "WITHDRAWN", product: {...pending.product, title: "Travel bag"}}, {...offer, entry_id: "paid", offer: {...offer.offer, status: "CAPTURED"}}]); show();
  await screen.findByRole("list", {name: "Current pool entries"});
  expect(screen.queryByText("Travel bag")).toBeNull();
  fireEvent.click(screen.getByRole("button", {name: "Past entries 2"}));
  expect(screen.getByText("You withdrew from this pool. This entry is no longer participating.")).toBeInTheDocument();
  expect(screen.getByText("Payment completed")).toBeInTheDocument();
  expect(screen.queryByRole("link", {name: "Review offer"})).toBeNull();
  expect(screen.getByRole("link", {name: "View order"})).toHaveAttribute("href", "/orders/order-one");
});
it("keeps references and backend states inside an optional disclosure", async () => {
  entries([pending]); show();
  const disclosure = (await screen.findByText("Entry details")).closest("details")!;
  expect(disclosure.open).toBe(false);
  fireEvent.click(screen.getByText("Entry details"));
  expect(within(disclosure).getByText("pool-one")).toBeInTheDocument();
  expect(within(disclosure).getByText("SUBMITTED")).toBeInTheDocument();
  expect(screen.getByRole("heading", {name: "27-inch monitor"})).toBeInTheDocument();
});
it("searches names in the loaded feed without another API call", async () => {
  entries([pending, waiting]); show(); await screen.findByText("Ceramic kettle");
  fireEvent.change(screen.getByLabelText("Search your pools"), {target: {value: "kettle"}});
  expect(screen.queryByRole("heading", {name: "27-inch monitor"})).toBeNull();
  expect(screen.getByRole("heading", {name: "Ceramic kettle"})).toBeInTheDocument();
  expect(transport.get).toHaveBeenCalledTimes(1);
});
it("offers recovery for an empty search", async () => {
  entries([pending]); show(); await screen.findByText("27-inch monitor");
  fireEvent.change(screen.getByLabelText("Search your pools"), {target: {value: "missing"}});
  expect(screen.getByRole("heading", {name: "No matching pools"})).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", {name: "Clear search"}));
  expect(screen.getByRole("heading", {name: "27-inch monitor"})).toBeInTheDocument();
});
it("explains a priced-out entry in history without treating it as a waiting-list seat", async () => {
  entries([{...waiting, allocation: {...waiting.allocation, status: "PRICED_OUT"}}]); show();
  fireEvent.click(await screen.findByRole("button", {name: "Past entries 1"}));
  expect(screen.getByText("Your price limit did not qualify for this lot. No seat was assigned.")).toBeInTheDocument();
  expect(screen.queryByText(/You're #/)).toBeNull();
});
// T09B04 acceptance 1 (F6): the cap is the number the AI proposed and the buyer
// confirmed, so a wrong cap must be tellable apart from a price that really was higher.
it("names the delivered price and the buyer's own confirmed limit when both are known", async () => {
  entries([{...waiting, allocation: {...waiting.allocation, status: "PRICED_OUT", item_cents: 47000, cap_cents: 44000}}]); show();
  fireEvent.click(await screen.findByRole("button", {name: "Past entries 1"}));
  expect(screen.getByText(/delivered price for this lot was \$470\.00/)).toBeInTheDocument();
  expect(screen.getByText(/confirmed limit was \$440\.00/)).toBeInTheDocument();
  expect(screen.getByText(/checked and confirmed after the AI proposed it/)).toBeInTheDocument();
});
it("loads without flashing a join or approval action", async () => {
  let finish!: (value: unknown) => void;
  transport.get.mockReturnValue(new Promise((resolve) => {finish = resolve;}));
  show(); expect(screen.getByRole("status", {name: "Loading your pools"})).toBeInTheDocument();
  expect(screen.queryByRole("link", {name: "Review offer"})).toBeNull();
  await act(async () => {finish({data: {items: [offer]}});});
  expect(await screen.findByRole("link", {name: "Review offer"})).toBeInTheDocument();
});
it("retries a failed history read without pretending the account has no pools", async () => {
  transport.get.mockResolvedValueOnce({error: {error: {code: "REQUEST_FAILED", message: "Try again."}}}).mockResolvedValueOnce({data: {items: [pending]}});
  show(); expect(await screen.findByRole("alert")).toHaveTextContent("Try again.");
  expect(screen.queryByText("No pools joined yet")).toBeNull();
  fireEvent.click(screen.getByRole("button", {name: "Try again"}));
  expect(await screen.findByRole("heading", {name: "27-inch monitor"})).toBeInTheDocument();
});
it("has an honest first-use empty state", async () => {
  entries([]); show();
  expect(await screen.findByRole("heading", {name: "No pools joined yet"})).toBeInTheDocument();
  expect(screen.getByRole("link", {name: "Find a pool"})).toHaveAttribute("href", "/discover");
});

it("keeps a cancelled pool without an order in history and explains its outcome", async () => {
  entries([{...pending, pool_status: "CANCELLED", labels: ["SANDBOX", "SIMULATED"]}]); show();
  fireEvent.click(await screen.findByRole("button", {name: "Past entries 1"}));
  expect(screen.getByText("This pool was cancelled. This entry is no longer participating.")).toBeInTheDocument();
  expect(screen.getByText("SIMULATED")).toBeInTheDocument();
  expect(screen.queryByRole("link", {name: "Review offer"})).toBeNull();
});

it("labels a simulated captured order instead of implying a real payment", async () => {
  entries([{...offer, labels: ["SANDBOX", "SIMULATED", "FALLBACK: single stand-in seller"], offer: {...offer.offer, status: "CAPTURED"}}]); show();
  fireEvent.click(await screen.findByRole("button", {name: "Past entries 1"}));
  expect(screen.getByText("SIMULATED")).toBeInTheDocument();
  expect(screen.getByText("FALLBACK: single stand-in seller")).toBeInTheDocument();
  expect(screen.getByText("Payment completed")).toBeInTheDocument();
});
