import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { type ApiComponents } from "../src/shared";
import { EntryReceiptPage } from "../src/buyer/receipt/EntryReceiptPage";
const pdf = vi.hoisted(() => ({ save: vi.fn() }));
vi.mock("../src/buyer/receipt/receiptPdf", () => ({ createReceiptPdf: () => pdf }));

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
  vi.unstubAllGlobals();
});

describe("the entry receipt page", () => {
  it("downloads a PDF with a PDF filename", async () => {
    pdf.save.mockReset();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, arrayBuffer: async () => new Uint8Array([1, 2]).buffer }));
    show();
    fireEvent.click(screen.getByRole("button", { name: "Download PDF" }));
    await waitFor(() => expect(pdf.save).toHaveBeenCalledWith("fairpool-entry-receipt-entry-one.pdf"));
    expect(screen.getByRole("status")).toHaveTextContent("PDF receipt downloaded");
  });
  it("offers recovery if PDF preparation fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    show();
    fireEvent.click(screen.getByRole("button", { name: "Download PDF" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Could not download the PDF"));
    expect(screen.getByRole("button", { name: "Download PDF" })).toBeEnabled();
  });
  it("shows useful receipt fields without exposing cryptographic proof", () => {
    show();
    expect(screen.getByRole("heading", { name: "Entry receipt" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "27-inch 4K monitor" })).toBeInTheDocument();
    expect(screen.getByText("Joining fee")).toBeInTheDocument();
    expect(screen.getByText("$0.00")).toHaveTextContent("$0.00 USD");
    expect(screen.getByText("Purchase payment")).toBeInTheDocument();
    for (const value of [receipt.payload.commitment, receipt.request_hash, receipt.salt_hex, receipt.signature]) expect(screen.queryByText(value)).toBeNull();
  });

  it("says plainly that an entry is not a payment, and that the proof is the server's", () => {
    show();
    expect(
      screen.getByText(/Joining did not charge you or place a hold/),
    ).toBeInTheDocument();
    expect(screen.getByText(/comes back whenever you open the pool/)).toBeInTheDocument();
  });

  it("copies a value and reports it", async () => {
    show();
    fireEvent.click(screen.getByRole("button", { name: "Copy receipt reference" }));
    await waitFor(() =>
      expect(navigator.clipboard.writeText).toHaveBeenCalledWith("entry-one"),
    );
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Receipt reference copied."));
  });

  it("tells the buyer to copy by hand when the browser will not", async () => {
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: vi.fn().mockRejectedValue(new Error("denied")) },
    });
    show();
    fireEvent.click(screen.getByRole("button", { name: "Copy receipt reference" }));
    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent(
        "Could not copy receipt reference. Select the value to copy it manually.",
      ),
    );
  });

  it("downloads the receipt with the signed payload unchanged", () => {
    vi.useFakeTimers();
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
      fireEvent.click(screen.getByRole("button", { name: "Signed proof (JSON)" }));
      expect(clicks).toEqual(["fairpool-entry-receipt-entry-one.json"]);
      expect(revoked).not.toHaveBeenCalled();
      vi.advanceTimersByTime(1000);
      expect(revoked).toHaveBeenCalledWith("blob:receipt");
      expect(
        screen.getByText("Receipt downloaded as a JSON file. Keep it: it proves this entry."),
      ).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
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
