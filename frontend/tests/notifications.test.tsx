import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const transport = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("../src/shared/api/client", () => ({
  api: { GET: transport.get, POST: transport.post },
  API_BASE_URL: "http://localhost:8000",
}));

import { NotificationInbox } from "../src/shared";

interface Item {
  id: string;
  kind: string;
  payload: Record<string, unknown>;
  created_at: string;
  read_at: string | null;
}

const CREATED = "2026-11-07T12:00:00Z";

function item(kind: string, payload: Record<string, unknown> = {}, id = kind): Item {
  return { id, kind, payload, created_at: CREATED, read_at: null };
}

let list: { items: Item[]; unread: number } = { items: [], unread: 0 };

beforeEach(() => {
  list = { items: [], unread: 0 };
  transport.get.mockReset();
  transport.post.mockReset();
  transport.get.mockImplementation(async () => ({ data: list, error: undefined }));
  transport.post.mockImplementation(async () => ({
    data: { marked: list.unread, unread: 0 },
    error: undefined,
  }));
});

afterEach(() => {
  vi.restoreAllMocks();
});

async function openInbox(): Promise<void> {
  render(<NotificationInbox />);
  fireEvent.click(screen.getByRole("button", { name: /Inbox/ }));
  await screen.findByRole("region", { name: "Notifications" });
}

describe("the notification inbox", () => {
  it("lists the owner's notifications, newest first, and marks them read", async () => {
    list = {
      items: [item("lot.awarded", {}, "newest"), item("bid.lost", {}, "older")],
      unread: 2,
    };
    await openInbox();

    const rows = await screen.findAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("Your bid won a lot.");
    expect(rows[1]).toHaveTextContent("Your bid was not selected for a lot.");
    expect(screen.getByRole("status")).toHaveTextContent("All read");
    expect(transport.get).toHaveBeenCalledWith("/api/v1/me/notifications");
    await waitFor(() =>
      expect(transport.post).toHaveBeenCalledWith("/api/v1/me/notifications/read"),
    );
  });

  it.each([
    ["lot.awarded", {}, "Your bid won a lot."],
    ["lot.cancelled", {}, "A lot you were part of was cancelled"],
    ["lot.funded", { completed_captures: 4 }, "reached its minimum with 4 buyers paid"],
    ["lot.closed", {}, "checkout window closed"],
    ["bid.lost", {}, "was not selected for a lot"],
    ["bid.rejected", { reason: "Delivery window is too short" }, "Delivery window is too short"],
    ["bid.flagged", {}, "flagged for a manual check"],
    ["buyer_order.offered", {}, "offer is waiting"],
    ["order.capture", {}, "payment was captured"],
    ["order.vault_charge", {}, "saved payment method is being charged"],
    ["refund", {}, "refund was completed"],
    ["entry.rejected", {}, "pool entry was not accepted"],
    ["buyer_order.rejected", {}, "offer could not go ahead"],
  ])("renders %s as a sentence", async (kind, payload, sentence) => {
    list = { items: [item(kind, payload)], unread: 1 };
    await openInbox();
    const rows = await screen.findAllByRole("listitem");
    expect(rows[0]).toHaveTextContent(sentence);
    // A dotted kind is an internal identifier and must never be the copy shown.
    if (kind.includes(".")) expect(rows[0]).not.toHaveTextContent(kind);
  });

  it("renders an unknown kind as a neutral line instead of raw JSON", async () => {
    list = { items: [item("some.future.kind", { secret: "raw-payload" })], unread: 1 };
    await openInbox();
    const rows = await screen.findAllByRole("listitem");
    expect(rows[0]).toHaveTextContent("You have a new notification.");
    expect(rows[0]).not.toHaveTextContent("some.future.kind");
    expect(rows[0]).not.toHaveTextContent("raw-payload");
  });

  it("shows the empty state when nothing was ever written", async () => {
    list = { items: [], unread: 0 };
    await openInbox();
    expect(await screen.findByText("No notifications yet.")).toBeInTheDocument();
    expect(screen.queryByRole("listitem")).toBeNull();
  });

  it("still asks the server to mark read when every row is already read", async () => {
    list = { items: [item("lot.funded", {}, "already-read")], unread: 0 };
    await openInbox();
    await screen.findByRole("listitem");
    await waitFor(() => expect(transport.post).toHaveBeenCalledTimes(1));
  });
});
