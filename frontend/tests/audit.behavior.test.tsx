/**
 * T09B01: the audit page recomputes, and reports what it found.
 *
 * The payloads below are built with the same `verify` module the page uses, so a pass
 * means the arithmetic agrees and a fail means the page said so out loud. The vectors
 * supply real hex values; nothing here trusts the served number it is checking.
 */
import { render, screen, fireEvent } from "@testing-library/react";
import { Link, MemoryRouter, Route, Routes } from "react-router-dom";
import { readFileSync } from "node:fs";
import path from "node:path";
import { beforeEach, expect, it, vi } from "vitest";

const transport = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("../src/shared/api/client", () => ({
  api: { GET: transport.get, POST: transport.post },
  API_BASE_URL: "http://localhost:8000",
}));

import { AuditPage } from "../src/audit/AuditPage";
import { commitment, merkleRoot, rulesHash } from "../src/audit/verify";
import { readClient, resetReadCache } from "../src/shared/api/reads";
import { resetSessionCache, setAccount } from "../src/shared/lib/session";

const vectors = JSON.parse(
  readFileSync(path.resolve(__dirname, "../../docs/contracts/vectors/fairness_v1.json"), "utf8"),
) as {
  entries: { entry_id: string; salt_hex: string; canonical_request: { pool_id: string }; request_hash: string; commitment: string }[];
  sorted_commitments: string[];
  order: string[];
  seed_hex: string;
  rules: { document: Record<string, unknown>; sha256: string };
};

const POOL_ID = "11111111-1111-4111-8111-111111111111";

async function auditPayload(overrides: Record<string, unknown> = {}) {
  const commitments = vectors.sorted_commitments;
  return {
    rules_hash: await rulesHash(vectors.rules.document),
    rules_document: vectors.rules.document,
    pool_status: "COMPLETED",
    entries_root: await merkleRoot(commitments),
    entries_count: commitments.length,
    commitments,
    beacon: { source: "drand", chain_hash: "ab".repeat(32), round: 41 },
    seed_hex: vectors.seed_hex,
    seed_is_demo: false,
    lots: [
      {
        lot_id: "22222222-2222-4222-8222-222222222222",
        zone_id: "US-EAST",
        lot_order: 1,
        seats: 3,
        status: "FUNDED",
        rank_range: [1, 3],
        bids_root: "ff".repeat(32),
        bids_count: 2,
        award: null,
      },
    ],
    audit_checkpoints: [],
    checkpoint: null,
    ...overrides,
  };
}

function show() {
  return render(
    <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }} initialEntries={[`/audit/${POOL_ID}`]}>
      <Routes>
        <Route path="/audit/:poolId" element={<AuditPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

const PUBLIC_KEY = (vectors as unknown as {receipt: {public_key_b64url: string}}).receipt.public_key_b64url;

function serve(payloads: Record<string, unknown>) {
  transport.get.mockImplementation(async (url: string) => {
    if (String(url).endsWith("/keys")) {
      return { data: { algorithm: "ed25519", public_key: PUBLIC_KEY } };
    }
    return { data: payloads };
  });
}

beforeEach(() => {
  resetSessionCache("out");
  resetReadCache();
  transport.get.mockReset();
  transport.post.mockReset();
});

it("loads only the signed-in buyer's saved receipt on request and prefills the local checker", async () => {
  resetSessionCache("in");
  setAccount({ role: "buyer", display_name: "Demo Buyer", paypal_linked: true });
  const payload = await auditPayload();
  const entry = vectors.entries[0]!;
  transport.get.mockImplementation(async (url: string) => {
    if (url.endsWith("/entries/me")) return { data: { receipt: { payload: { pool_id: POOL_ID, entry_id: entry.entry_id }, request_hash: entry.request_hash, salt_hex: entry.salt_hex } } };
    if (url.endsWith("/keys")) return { data: { public_key: PUBLIC_KEY } };
    if (url.endsWith("/notifications")) return { data: { items: [], unread: 0 } };
    return { data: payload };
  });
  show();
  const useReceipt = await screen.findByRole("button", { name: "Use my saved receipt" });
  expect(transport.get.mock.calls.some(([url]) => String(url).endsWith("/entries/me"))).toBe(false);
  fireEvent.click(useReceipt);
  expect(await screen.findByDisplayValue(entry.entry_id)).toBeInTheDocument();
  expect(screen.getByLabelText("Request hash")).toHaveValue(entry.request_hash);
  expect(screen.getByLabelText("Salt")).toHaveValue(entry.salt_hex);
  expect(transport.post).not.toHaveBeenCalled();
});

it("requires a new receipt request after navigating to another pool even when its receipt is cached", async () => {
  resetSessionCache("in");
  setAccount({ role: "buyer", display_name: "Demo Buyer", paypal_linked: true });
  const payload = await auditPayload();
  const entry = vectors.entries[0]!;
  const otherPool = "33333333-3333-4333-8333-333333333333";
  readClient.setQueryData([`/api/v1/pools/${otherPool}/entries/me`], { receipt: { payload: { pool_id: otherPool, entry_id: "cached-other-entry" }, request_hash: entry.request_hash, salt_hex: entry.salt_hex } });
  transport.get.mockImplementation(async (url: string) => {
    if (url.endsWith("/entries/me")) return { data: { receipt: { payload: { pool_id: POOL_ID, entry_id: entry.entry_id }, request_hash: entry.request_hash, salt_hex: entry.salt_hex } } };
    if (url.endsWith("/keys")) return { data: { public_key: PUBLIC_KEY } };
    if (url.endsWith("/notifications")) return { data: { items: [], unread: 0 } };
    return { data: payload };
  });
  render(<MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }} initialEntries={[`/audit/${POOL_ID}`]}>
    <Link to={`/audit/${otherPool}`}>Another pool</Link>
    <Routes><Route path="/audit/:poolId" element={<AuditPage />} /></Routes>
  </MemoryRouter>);
  fireEvent.click(await screen.findByRole("button", { name: "Use my saved receipt" }));
  await screen.findByDisplayValue(entry.entry_id);
  fireEvent.click(screen.getByRole("link", { name: "Another pool" }));
  expect(await screen.findByLabelText("Entry id")).toHaveValue("");
  expect(screen.queryByDisplayValue("cached-other-entry")).toBeNull();
});

it("puts the private receipt check before the supporting draw and exposes page navigation", async () => {
  serve(await auditPayload());
  show();
  const checker = await screen.findByRole("heading", { name: "Check your own place" });
  const draw = screen.getByRole("heading", { name: "The draw" });
  expect(checker.compareDocumentPosition(draw) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(screen.getByRole("navigation", { name: "Audit sections" })).toBeInTheDocument();
});

it("keeps unpublished counts unknown and waits for the seed after entry close", async () => {
  serve(await auditPayload({ seed_hex: null, entries_count: null, entries_root: null, commitments: [], lots: [] }));
  show();
  expect(await screen.findByText("Seed not yet public. It stays private while lots can still receive bids.")).toBeInTheDocument();
  expect(screen.getByLabelText("Published evidence")).toHaveTextContent(/Entries published.*not yet published/);
  const entry = vectors.entries[0]!;
  fireEvent.change(screen.getByLabelText("Entry id"), {target: {value: entry.entry_id}});
  fireEvent.change(screen.getByLabelText("Request hash"), {target: {value: entry.request_hash}});
  fireEvent.change(screen.getByLabelText("Salt"), {target: {value: entry.salt_hex}});
  fireEvent.click(screen.getByRole("button", {name: "Recompute my place"}));
  expect(screen.getByTestId("audit-place")).toHaveTextContent("when the seed is public, after entry and bidding windows have closed");
  expect(transport.post).not.toHaveBeenCalled();
});

it("reports that the published rules document hashes to the served hash", async () => {
  serve(await auditPayload());
  show();
  expect(await screen.findByText("Tamper seal")).toBeInTheDocument();
  expect(await screen.findAllByLabelText("Check passed")).toHaveLength(2);
  expect(screen.getByText(/rebuild the published fingerprint/)).toBeInTheDocument();
  expect(screen.queryByText(/does not match/)).toBeNull();
});

it("says so plainly when a served number does not recompute", async () => {
  const truth = await auditPayload();
  const tampered = { ...truth, rules_hash: "0".repeat(64) };
  serve(tampered);
  show();
  expect(await screen.findByText(/Served 000000000000/)).toBeInTheDocument();
  expect(await screen.findAllByLabelText("Check failed")).toHaveLength(1);
});

it("marks a demo seed as chosen by FairPool", async () => {
  serve(await auditPayload({ seed_is_demo: true }));
  show();
  expect(await screen.findByText("DEMO SEED")).toBeInTheDocument();
});

it("publishes the bid-set root and the number of bids per lot", async () => {
  serve(await auditPayload());
  show();
  const table = await screen.findByRole("table");
  expect(screen.getByRole("columnheader", {name: "Bid seal"})).toBeInTheDocument();
  expect(table).toHaveTextContent(`${"ff".repeat(6)}…`);
  expect(table).toHaveTextContent("2");
});

it("computes a buyer's rank from their own receipt fields", async () => {
  const entry = vectors.entries[0]!;
  const mine = await commitment(POOL_ID, entry.entry_id, entry.request_hash, entry.salt_hex);
  const list = [...vectors.sorted_commitments].sort();
  // Lot 1 covers every published rank, so the in-lot branch is the one under test.
  const lots = [{...((await auditPayload()).lots as Record<string, unknown>[])[0]!, rank_range: [1, list.length]}];
  serve(await auditPayload({commitments: list, lots}));
  show();
  await screen.findByText("Tamper seal");

  fireEvent.change(screen.getByLabelText("Entry id"), {target: {value: entry.entry_id}});
  fireEvent.change(screen.getByLabelText("Request hash"), {target: {value: entry.request_hash}});
  fireEvent.change(screen.getByLabelText("Salt"), {target: {value: entry.salt_hex}});
  fireEvent.click(screen.getByRole("button", {name: "Recompute my place"}));

  // The recompute is async, so wait on its text rather than on the empty live region.
  const result = await screen.findByText(/listed at position/, {
    selector: '[data-testid="audit-place"]',
  });
  expect(result).toHaveTextContent(`listed at position ${list.indexOf(mine) + 1} of ${list.length}`);
  // The vector's rank order is the draw, so the page's rank must match it exactly.
  expect(result).toHaveTextContent(`your rank is ${vectors.order.indexOf(entry.entry_id) + 1}`);
  expect(result).toHaveTextContent(`ranks 1–${list.length}`);
  expect(result).toHaveTextContent("which falls inside lot 1");
});

it("says so when a receipt is not in the published list", async () => {
  const entry = vectors.entries[0]!;
  serve(await auditPayload());
  show();
  await screen.findByText("Tamper seal");

  // A different entry id over the same request is a commitment nobody published.
  fireEvent.change(screen.getByLabelText("Entry id"), {target: {value: "00000000-0000-4000-8000-000000000000"}});
  fireEvent.change(screen.getByLabelText("Request hash"), {target: {value: entry.request_hash}});
  fireEvent.change(screen.getByLabelText("Salt"), {target: {value: entry.salt_hex}});
  fireEvent.click(screen.getByRole("button", {name: "Recompute my place"}));

  // A string matcher means "whole element text", so the sentence is matched as a regex.
  expect(
    await screen.findByText(/is not in the published list of \d+/, {
      selector: '[data-testid="audit-place"]',
    }),
  ).toHaveTextContent(`published list of ${vectors.sorted_commitments.length}`);
});

it("states what the page cannot prove", async () => {
  serve(await auditPayload());
  show();
  expect(await screen.findByText(/not provably fair/)).toBeInTheDocument();
  expect(screen.getByText(/does not verify that signature/)).toBeInTheDocument();
});

it("keeps the audit context and offers recovery when its read fails", async () => {
  transport.get.mockResolvedValue({ error: { error: { code: "INTERNAL_ERROR" } } });
  show();
  expect(await screen.findByRole("heading", { name: "Public audit" })).toBeInTheDocument();
  expect(await screen.findByRole("button", { name: "Retry audit" })).toBeInTheDocument();
});
