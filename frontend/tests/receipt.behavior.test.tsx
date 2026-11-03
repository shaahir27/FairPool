import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { type ApiComponents } from "../src/shared";
import { EntryReceiptPage } from "../src/buyer/receipt/EntryReceiptPage";

type EntryReceipt = ApiComponents["schemas"]["EntryReceipt"];

const receipt: EntryReceipt = {
  payload: {
    v: 1,
    commitment: "c".repeat(64),
    entry_id: "entry-one",
    pool_id: "pool-one",
    received_at: "2026-11-02T10:03:00.000000Z",
  },
  salt_hex: "s".repeat(64),
  request_hash: "r".repeat(64),
  signature: "sig-base64url",
};

function show(onBack = vi.fn()) {
  return render(
    <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <EntryReceiptPage receipt={receipt} poolTitle="27-inch 4K monitor" onBack={onBack} />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText: vi.fn().mockResolvedValue(undefined) },
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("the entry receipt page", () => {
  it("names all seven values the pool signed", () => {
    show();
    expect(screen.getByRole("heading", { name: "Entry receipt" })).toBeInTheDocument();
    expect(screen.getByText(/27-inch 4K monitor/)).toBeInTheDocument();
    for (const label of [
      "Commitment",
      "Entry ID",
      "Pool ID",
      "Received time",
      "Salt",
      "Request hash",
      "Signature",
    ]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    expect(screen.getByText("c".repeat(64))).toBeInTheDocument();
    expect(screen.getByText("entry-one")).toBeInTheDocument();
    // The received time is stated twice on purpose: once in the header line, once in the
    // signed table below it.
    expect(screen.getAllByText(/Nov 2, 2026/)).toHaveLength(2);
    expect(screen.getByText("Keeps your fingerprint private")).toBeInTheDocument();
  });

  it("says plainly that an entry is not a payment, and that the proof is the server's", () => {
    show();
    expect(
      screen.getByText(/Nothing has been charged and no hold placed/),
    ).toBeInTheDocument();
    expect(screen.getByText(/comes back whenever you open the pool/)).toBeInTheDocument();
  });

  it("copies a value and reports it", async () => {
    show();
    fireEvent.click(screen.getByRole("button", { name: "Copy commitment" }));
    await waitFor(() =>
      expect(navigator.clipboard.writeText).toHaveBeenCalledWith("c".repeat(64)),
    );
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Commitment copied."));
  });

  it("tells the buyer to copy by hand when the browser will not", async () => {
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: vi.fn().mockRejectedValue(new Error("denied")) },
    });
    show();
    fireEvent.click(screen.getByRole("button", { name: "Copy salt" }));
    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent(
        "Could not copy salt. Select the value to copy it manually.",
      ),
    );
  });

  it("downloads the receipt with the signed payload unchanged", () => {
    const written: string[] = [];
    const RealBlob = Blob;
    class CapturedBlob extends RealBlob {
      constructor(parts: BlobPart[], options?: BlobPropertyBag) {
        super(parts, options);
        written.push(String(parts[0]));
      }
    }
    Object.defineProperty(globalThis, "Blob", { configurable: true, value: CapturedBlob });
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: vi.fn(() => "blob:receipt"),
    });
    const revoked = vi.fn();
    Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: revoked });
    const clicks: string[] = [];
    const originalClick = HTMLAnchorElement.prototype.click;
    HTMLAnchorElement.prototype.click = function patched(this: HTMLAnchorElement) {
      clicks.push(this.download);
    };
    try {
      show();
      fireEvent.click(screen.getByRole("button", { name: "Download receipt" }));
      expect(clicks).toEqual(["fairpool-entry-receipt-entry-one.json"]);
      expect(revoked).toHaveBeenCalledWith("blob:receipt");
      expect(
        screen.getByText("Receipt downloaded as a JSON file. Keep it: it proves this entry."),
      ).toBeInTheDocument();
    } finally {
      HTMLAnchorElement.prototype.click = originalClick;
      Object.defineProperty(globalThis, "Blob", { configurable: true, value: RealBlob });
    }
    // The payload in the file is the receipt exactly as it arrived, so the signature the
    // pool issued still covers the copy the buyer keeps.
    const parsed = JSON.parse(written[0] ?? "{}") as {
      kind: string;
      receipt: EntryReceipt;
      verify: { public_keys: string };
    };
    expect(parsed.kind).toBe("fairpool.entry_receipt");
    expect(parsed.receipt).toEqual(receipt);
    expect(parsed.verify.public_keys).toBe("/api/v1/public/keys");
  });

  it("prints on request", () => {
    const print = vi.fn();
    Object.defineProperty(window, "print", { configurable: true, value: print });
    show();
    fireEvent.click(screen.getByRole("button", { name: "Print" }));
    expect(print).toHaveBeenCalled();
  });

  it("links the receipt to the pool's own audit page", () => {
    show();
    expect(screen.getByRole("link", { name: "Check it on the public audit page" })).toHaveAttribute(
      "href",
      "/audit/pool-one",
    );
  });

  it("leaves the receipt by returning to the pool screen that opened it", () => {
    const onBack = vi.fn();
    show(onBack);
    fireEvent.click(screen.getByRole("button", { name: /Back to the pool/ }));
    expect(onBack).toHaveBeenCalledOnce();
  });
});
