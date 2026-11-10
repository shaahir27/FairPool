import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const transport = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("../src/shared/api/client", () => ({
  api: { GET: transport.get, POST: transport.post },
  API_BASE_URL: "http://localhost:8000",
}));

import { DiscoverPage, JOIN_BADGE } from "../src/buyer/discover/DiscoverPage";

/**
 * FR-UI-01 fixes the badge wording, so the literal is written out here rather than
 * read back from the component: a test that compares the screen to the same constant
 * the screen uses would pass even if the constant were wrong.
 */
const BADGE = "$0 to join. No hold until a merchant meets your price and you approve.";
const PLACEHOLDER = "What are you looking for and what is your max price?";

function pool(overrides: Record<string, unknown> = {}) {
  return {
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
    close_at: "2026-11-05T18:00:00Z",
    ...overrides,
  };
}

const confirmationCard = {
  proposal_id: "proposal-one",
  pool: {
    id: "pool-one",
    title: "27-inch 4K monitor",
    variant: "black",
    condition: "NEW",
    latest_delivery: "2026-11-17",
  },
  delivery: { zone_id: "US-EAST", region: "NY" },
  required_by: "2026-11-30",
  max_total_cents: 60000,
  firm: ["matte screen"],
  preferences: ["black bezel"],
  notices: {
    no_charge:
      "Nothing is charged now. A merchant and an exact price are confirmed first, you are never charged above the maximum you set here, and any payment follows your own approval of that offer.",
    lots_may_differ:
      "Separate lots in this pool can end with different winning merchants and prices.",
  },
};

function show() {
  return render(
    <MemoryRouter
      future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      initialEntries={["/"]}
    >
      <Routes>
        <Route path="/" element={<DiscoverPage />} />
        <Route path="/pools/:poolId" element={<div>lobby for :poolId</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

function ask(text: string) {
  fireEvent.change(screen.getByLabelText(PLACEHOLDER), { target: { value: text } });
  fireEvent.click(screen.getByRole("button", { name: "Find matches" }));
}

beforeEach(() => {
  sessionStorage.clear();
  transport.get.mockReset().mockResolvedValue({ data: [pool()] });
  transport.post.mockReset();
});

describe("Discover and Join", () => {
  it("prefills an example and focuses the request so the buyer can finish it", async () => {
    show();
    fireEvent.click(await screen.findByRole("button", { name: "Monitor under $600" }));
    expect(screen.getByLabelText(PLACEHOLDER)).toHaveValue("A 27-inch 4K monitor, matte screen, under $600, delivered to New York");
    expect(screen.getByLabelText(PLACEHOLDER)).toHaveFocus();
    expect(transport.post).not.toHaveBeenCalled();
  });
  it("groups each product's participation and delivery facts for comparison", async () => {
    transport.get.mockResolvedValue({ data: [pool({ entry_count: 18, delivery_regions: ["NY", "NJ"], delivery_sla_days: 7, min_return_days: 30 })] });
    show();
    const card = await screen.findByRole("article", { name: "27-inch 4K monitor" });
    const participation = within(card).getByLabelText("Pool participation");
    expect(participation).toHaveTextContent("18 entries");
    expect(participation).toHaveTextContent("Pool capacity");
    expect(participation).toHaveTextContent("Pool minimum");
    expect(within(card).getByLabelText("Delivery and returns")).toHaveTextContent("NY, NJ");
    expect(within(card).getByRole("link", { name: "View pool" })).toHaveAttribute("href", "/pools/pool-one");
    expect(within(card).getByText(BADGE)).toBeInTheDocument();
  });

  it("shows actual entry demand and published delivery requirements without implying a sale price", async () => {
    transport.get.mockResolvedValue({ data: [pool({ entry_count: 18, delivery_regions: ["NY", "NJ"], delivery_sla_days: 7, min_return_days: 30, bundle_contents: ["Monitor", "Stand"] })] });
    show();
    expect(await screen.findByText("18 entries")).toBeInTheDocument();
    expect(screen.getByText(/NY, NJ/)).toBeInTheDocument();
    expect(screen.getByText(/Within 7 days/)).toBeInTheDocument();
    expect(screen.getByText("Minimum returns")).toBeInTheDocument();
    expect(screen.getByText("30 days")).toBeInTheDocument();
    expect(screen.getByText("Price set after bidding")).toBeInTheDocument();
  });

  it("shows a reported zero entry count without inventing one for older responses", async () => {
    transport.get.mockResolvedValue({ data: [pool({ entry_count: 0 }), pool({ pool_id: "pool-two", title: "Desk lamp", entry_count: null })] });
    show();
    expect(await screen.findAllByText("0 entries")).toHaveLength(1);
  });

  it("does not report empty availability when the catalogue read fails", async () => {
    transport.get.mockResolvedValue({ error: { error: { code: "INTERNAL_ERROR" } } });
    show();
    await screen.findByRole("alert");
    expect(screen.queryByText("No open pools to join right now.")).toBeNull();
    expect(screen.getByRole("status", { name: "Pool search results" })).not.toHaveTextContent(/0 pools/);
  });

  it("makes the product name a destination and states its published delivery zone", async () => {
    show();
    const heading = await screen.findByRole("heading", { name: "27-inch 4K monitor" });
    expect(within(heading).getByRole("link")).toHaveAttribute("href", "/pools/pool-one");
    expect(screen.getByText(/US-EAST/)).toBeInTheDocument();
  });

  it("takes the request shortcut to the existing field without leaving discovery", async () => {
    show();
    await screen.findByRole("heading", { name: "27-inch 4K monitor" });
    fireEvent.click(screen.getByRole("button", { name: "Make a request" }));
    expect(screen.getByLabelText(PLACEHOLDER)).toHaveFocus();
    expect(transport.post).not.toHaveBeenCalled();
  });

  it("keeps Enter available for a multiline request instead of submitting it", async () => {
    show();
    await screen.findByRole("heading", { name: "27-inch 4K monitor" });
    const input = screen.getByLabelText(PLACEHOLDER);
    fireEvent.change(input, { target: { value: "A monitor\nunder $600" } });
    expect(fireEvent.keyDown(input, { key: "Enter" })).toBe(true);
    expect(transport.post).not.toHaveBeenCalled();
  });

  it("filters the loaded catalogue without losing pools when the search is cleared", async () => {
    transport.get.mockResolvedValue({
      data: [pool(), pool({ pool_id: "pool-two", title: "Ceramic kettle", product_key: "kettle" })],
    });
    show();
    await screen.findByRole("heading", { name: "Ceramic kettle" });
    const search = screen.getByRole("searchbox", { name: "Search open pools" });
    fireEvent.change(search, { target: { value: "kettle" } });
    expect(screen.getByRole("status", { name: "Pool search results" })).toHaveTextContent("1 of 2 pools matches your search");
    expect(screen.queryByRole("heading", { name: "27-inch 4K monitor" })).toBeNull();
    expect(screen.getByRole("heading", { name: "Ceramic kettle" })).toBeInTheDocument();
    fireEvent.change(search, { target: { value: "does not exist" } });
    expect(screen.getByText("No pools match your search.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Clear search" }));
    expect(screen.getByRole("heading", { name: "27-inch 4K monitor" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Ceramic kettle" })).toBeInTheDocument();
  });

  it("states the badge on every card, in the words the spec fixes", async () => {
    transport.get.mockResolvedValue({
      data: [pool(), pool({ pool_id: "pool-two", title: "Ceramic kettle" })],
    });
    show();
    const cards = await screen.findAllByText(BADGE);
    expect(cards).toHaveLength(2);
    expect(JOIN_BADGE).toBe(BADGE);
    expect(screen.getByRole("heading", { level: 1, name: "Open pools" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "Ceramic kettle" })).toBeInTheDocument();
    expect(screen.getAllByRole("searchbox", { name: "Search open pools" })).toHaveLength(1);
    expect(screen.getByRole("heading", { name: "Make a request" })).toBeInTheDocument();
    expect(screen.getByLabelText(PLACEHOLDER)).toBeInTheDocument();
  });

  it("filters the catalogue by a category derived from each pool's product key", async () => {
    transport.get.mockResolvedValue({
      data: [pool(), pool({ pool_id: "pool-two", title: "Ceramic kettle", product_key: "kettle-brew-1" })],
    });
    show();
    await screen.findByRole("heading", { name: "Ceramic kettle" });
    const group = screen.getByRole("group", { name: "Filter by category" });
    expect(within(group).getByRole("button", { name: "Monitor" })).toBeInTheDocument();
    expect(within(group).getByRole("button", { name: "Kettle" })).toBeInTheDocument();
    fireEvent.click(within(group).getByRole("button", { name: "Kettle" }));
    expect(screen.getByRole("heading", { name: "Ceramic kettle" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "27-inch 4K monitor" })).toBeNull();
    fireEvent.click(within(group).getByRole("button", { name: "All pools" }));
    expect(screen.getByRole("heading", { name: "27-inch 4K monitor" })).toBeInTheDocument();
  });

  it("asks for the pools that are open, ordered by entry count", async () => {
    show();
    await screen.findByText("27-inch 4K monitor");
    const [path, init] = transport.get.mock.calls[0] ?? [];
    expect(path).toBe("/api/v1/pools");
    expect(init).toMatchObject({ params: { query: { status: "OPEN", sort: "trending" } } });
  });

  it("shows a loading state before the grid arrives", () => {
    transport.get.mockReturnValue(new Promise(() => {}));
    show();
    expect(screen.getByRole("status", { name: "Loading open pools" })).toBeInTheDocument();
  });

  it("says plainly when nothing is open", async () => {
    transport.get.mockResolvedValue({ data: [] });
    show();
    expect(await screen.findByText("No open pools to join right now.")).toBeInTheDocument();
  });

  it("offers a reload when the list fails", async () => {
    transport.get.mockResolvedValue({ error: { error: { code: "INTERNAL_ERROR", message: "x" } } });
    show();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "We couldn’t load the open pools. Try again.",
    );
    fireEvent.click(screen.getByRole("button", { name: "Reload pools" }));
    await waitFor(() => expect(transport.get).toHaveBeenCalledTimes(2));
  });

  it("keeps the conversation going when intake needs one more answer", async () => {
    transport.post.mockResolvedValue({
      data: {
        session_id: "session-one",
        status: "NEEDS_CLARIFICATION",
        clarifying_question: "By which date do you need it (YYYY-MM-DD)?",
        confirmation_card: null,
      },
    });
    show();
    await screen.findByText("27-inch 4K monitor");
    ask("a monitor for my desk");
    expect(await screen.findByText("By which date do you need it (YYYY-MM-DD)?")).toBeInTheDocument();
    const body = transport.post.mock.calls[0]?.[1] as { body: { session_id: string | null } };
    expect(body.body.session_id).toBeNull();
  });

  it("renders the server's card with its notices word for word and confirms into the lobby", async () => {
    transport.post
      .mockResolvedValueOnce({
        data: {
          session_id: "session-one",
          status: "READY_TO_CONFIRM",
          clarifying_question: null,
          confirmation_card: confirmationCard,
        },
      })
      .mockResolvedValueOnce({
        data: { confirmed_request_id: "request-one", canonical_request: {} },
      });
    show();
    await screen.findByText("27-inch 4K monitor");
    ask("27-inch 4K monitor, matte screen, under $600, needed by 30 November, delivered to NY");

    expect(await screen.findByText(confirmationCard.notices.no_charge)).toBeInTheDocument();
    expect(screen.getAllByRole("heading", { level: 2, name: "27-inch 4K monitor" })).toHaveLength(2);
    expect(screen.getByText(confirmationCard.notices.lots_may_differ)).toBeInTheDocument();
    expect(screen.getByText("$600.00 USD")).toBeInTheDocument();
    expect(screen.getByText("Firm requirement: matte screen")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Confirm and continue" }));
    expect(await screen.findByText("lobby for :poolId")).toBeInTheDocument();
    const [path, init] = transport.post.mock.calls[1] ?? [];
    expect(path).toBe("/api/v1/intake/confirm");
    expect(init).toEqual({ body: { proposal_id: "proposal-one" } });
    expect(sessionStorage.getItem("fairpool.entry.pending.pool-one")).toBe('"request-one"');
  });

  it("says plainly when no open pool matches, and never invents one", async () => {
    transport.post.mockResolvedValue({
      data: {
        session_id: "session-one",
        status: "NO_MATCH",
        clarifying_question: null,
        confirmation_card: null,
      },
    });
    show();
    await screen.findByText("27-inch 4K monitor");
    ask("a submarine");
    expect(
      await screen.findByText(/No open pool matches that yet/),
    ).toBeInTheDocument();
    expect(screen.queryByText("Confirm your request")).not.toBeInTheDocument();
  });

  it("renders the server's manual-form instruction instead of its own no-match line", async () => {
    const instruction =
      "I could not turn that into a request for an open pool. You can still enter with the manual form.";
    transport.post.mockResolvedValue({
      data: {
        session_id: "session-one",
        status: "NO_MATCH",
        clarifying_question: instruction,
        confirmation_card: null,
      },
    });
    show();
    await screen.findByText("27-inch 4K monitor");
    ask("a submarine");
    expect(await screen.findByText(instruction)).toBeInTheDocument();
    expect(screen.queryByText(/No open pool matches that yet/)).not.toBeInTheDocument();
    expect(screen.getByLabelText(PLACEHOLDER)).toHaveValue("a submarine");
    fireEvent.change(screen.getByLabelText("Choose a pool for manual entry"), { target: { value: "pool-one" } });
    expect(screen.getByRole("link", { name: "Fill in my request" })).toHaveAttribute("href", "/pools/pool-one#pool-entry");
  });

  it("shows the API's own error when intake refuses", async () => {
    transport.post.mockResolvedValue({
      error: { error: { code: "RATE_LIMITED", message: "Over the limit." } },
    });
    show();
    await screen.findByText("27-inch 4K monitor");
    ask("anything at all");
    expect(await screen.findByRole("alert")).toHaveTextContent("RATE_LIMITED");
  });
});


it("returns to Discover without waiting for the same catalogue again", async () => {
  const first = show();
  await screen.findByRole("heading", {name: "27-inch 4K monitor"});
  first.unmount();
  transport.get.mockReturnValue(new Promise(() => {}));
  show();
  expect(screen.getByRole("heading", {name: "27-inch 4K monitor"})).toBeInTheDocument();
  expect(transport.get).toHaveBeenCalledTimes(1);
});
