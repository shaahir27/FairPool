import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { createReceiptPdf } from "../src/buyer/receipt/receiptPdf";

describe("downloadable receipt PDF", () => {
  it("keeps multiline product details and summary text inside every page", () => {
    const font = readFileSync("public/fonts/noto-sans-receipt.ttf").toString("base64");
    const receipt = { payload: { v: 1 as const, entry_id: "entry-test", pool_id: "pool-test", received_at: "2026-11-03T12:00:00Z", commitment: "c".repeat(64) }, request_hash: "r".repeat(64), salt_hex: "a".repeat(64), signature: "signature-test" };
    const doc = createReceiptPdf(receipt, "Monitor\n".repeat(21), font);
    const coordinates = [...doc.output().matchAll(/\n([\d.-]+) ([\d.-]+) Td\n/g)];
    expect(coordinates.length).toBeGreaterThan(10);
    for (const [, x, y] of coordinates) {
      expect(Number(x)).toBeGreaterThanOrEqual(0);
      expect(Number(y)).toBeGreaterThan(0);
      expect(Number(y)).toBeLessThan(842);
    }
  });
  it("refuses silent text loss with the actual bundled font", () => {
    const font = readFileSync("public/fonts/noto-sans-receipt.ttf").toString("base64");
    const receipt = { payload: { v: 1 as const, entry_id: "entry-test", pool_id: "pool-test", received_at: "2026-11-03T12:00:00Z", commitment: "c".repeat(64) }, request_hash: "r".repeat(64), salt_hex: "a".repeat(64), signature: "signature-test" };
    expect(() => createReceiptPdf(receipt, "Café", font)).not.toThrow();
    for (const name of ["王", "श", "ஷ"]) expect(() => createReceiptPdf(receipt, "Monitor", font, [["Account name", name]])).toThrow("Use Print");
  });
  it("creates an actual PDF with receipt details and safe entry-only claims", () => {
    const doc = createReceiptPdf({ payload: { v: 1 as const, entry_id: "entry-test", pool_id: "pool-test", received_at: "2026-11-03T12:00:00Z", commitment: "c".repeat(64) }, request_hash: "r".repeat(64), salt_hex: "a".repeat(64), signature: "signature-test" }, "Monitor");
    const bytes = doc.output();
    expect(bytes.startsWith("%PDF-")).toBe(true);
    expect(bytes.trimEnd().endsWith("%%EOF")).toBe(true);
    for (const value of ["entry-test", "pool-test", "Monitor", "FairPool", "not a payment receipt"]) expect(bytes).toContain(value);
    expect(bytes).not.toContain("signature-test");
    expect(bytes).not.toContain("c".repeat(64));
    expect(doc.getNumberOfPages()).toBeLessThanOrEqual(2);
  });
});
