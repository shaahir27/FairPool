import { jsPDF } from "jspdf";
import type { ApiComponents } from "../../shared";

type Receipt = ApiComponents["schemas"]["EntryReceipt"];

/** A readable entry acknowledgement; the separate JSON retains the signed proof. */
export function createReceiptPdf(receipt: Receipt, title: string, fontData?: string, details: [string, string][] = []) {
  const pdf = new jsPDF({ unit: "mm", format: "a4" });
  if (fontData) {
    pdf.addFileToVFS("NotoSans.ttf", fontData);
    pdf.addFont("NotoSans.ttf", "NotoSans", "normal");
    pdf.setFont("NotoSans", "normal");
    const font = pdf.getFont().metadata as { characterToGlyph: (code: number) => number };
    for (const value of [title, ...details.map(([, value]) => value)]) {
      for (const character of value) {
        if (!/\s/u.test(character) && !font.characterToGlyph(character.codePointAt(0)!)) {
          throw new Error("Use Print to preserve characters not supported by the PDF font");
        }
      }
    }
    pdf.setFont("helvetica", "normal");
  }
  pdf.setProperties({ title: "FairPool entry receipt", author: "FairPool" });
  const bodyFont = fontData ? "NotoSans" : "helvetica";
  const values = new Map(details);
  const ink = () => pdf.setTextColor(23, 54, 76);
  const muted = () => pdf.setTextColor(58, 83, 105);
  function lines(value: string, width: number, size: number): string[] {
    pdf.setFont(bodyFont, "normal"); pdf.setFontSize(size);
    return pdf.splitTextToSize(value.replace(/\s+/gu, " ").trim() || "-", width);
  }
  function height(value: string, width: number, size = 10) { return lines(value, width, size).length * size * .48; }
  function space(y: number, required: number) {
    if (required > 246) throw new Error("Use Print for unusually long receipt content");
    if (y + required <= 270) return y;
    pdf.addPage(); return 24;
  }
  function write(value: string, x: number, y: number, width: number, size = 10) {
    const rows = lines(value, width, size);
    pdf.setFont(bodyFont, "normal"); pdf.setFontSize(size); ink();
    for (const line of rows) {
      pdf.text(line, x, y); y += size * .48;
    }
    return y;
  }
  function caption(value: string, x: number, y: number) {
    pdf.setFont("helvetica", "bold"); pdf.setFontSize(8); muted(); pdf.text(value, x, y);
  }
  function rule(y: number) { pdf.setDrawColor(204, 218, 228); pdf.setLineWidth(.3); pdf.line(18, y, 192, y); }
  pdf.setFillColor(8, 111, 165); pdf.rect(0, 0, 210, 3, "F");
  // PoolMark is embedded as vectors for sharp printing.
  pdf.roundedRect(18, 17, 13, 13, 3, 3, "F");
  pdf.setDrawColor(201, 230, 243); pdf.setLineWidth(.9);
  pdf.circle(24.5, 22.8, 3); pdf.line(21.5, 22.8, 21.5, 28);
  pdf.setFillColor(255, 195, 79); pdf.circle(24.5, 22.8, 1.1, "F");
  pdf.setFont("helvetica", "normal"); pdf.setFontSize(20); ink(); pdf.text("FairPool", 35, 26);
  pdf.setFontSize(22); pdf.text("Entry receipt", 192, 25, { align: "right" });
  pdf.setFontSize(9); muted(); pdf.text("PAYPAL SANDBOX", 192, 32, { align: "right" });
  rule(40);
  caption("RECEIPT REFERENCE", 18, 51);
  const refEnd = write(receipt.payload.entry_id, 18, 58, 82, 9);
  caption("RECEIVED AT (UTC)", 112, 51);
  const dateEnd = write(receipt.payload.received_at, 112, 58, 80, 9);
  let y = Math.max(refEnd, dateEnd) + 10;
  y = space(y, 7 + Math.max(height(values.get("Account name") ?? "Signed-in pool participant", 82), height(values.get("Current entry status") ?? "See pool for current status", 80)) + 11);
  caption("ACCOUNT", 18, y);
  const accountEnd = write(values.get("Account name") ?? "Signed-in pool participant", 18, y + 7, 82);
  caption("CURRENT ENTRY STATUS", 112, y);
  const statusEnd = write(values.get("Current entry status") ?? "See pool for current status", 112, y + 7, 80);
  y = Math.max(accountEnd, statusEnd) + 11;
  const productInfo = [values.get("Condition"), values.get("Variant")].filter(Boolean).join(" / ");
  y = space(y, 19 + height(title, 126, 13) + 3 + (productInfo ? height(productInfo, 126, 9) : 0) + 21);
  pdf.setFillColor(232, 243, 249); pdf.rect(18, y, 174, 10, "F");
  caption("POOL ITEM", 22, y + 6.5); caption("JOINING FEE", 162, y + 6.5);
  y += 19;
  const productEnd = write(title, 22, y, 126, 13);
  pdf.setFont("helvetica", "bold"); pdf.setFontSize(11); ink(); pdf.text("$0.00 USD", 188, y, { align: "right" });
  y = productEnd + 3;
  if (productInfo) y = write(productInfo, 22, y, 126, 9);
  y += 8; rule(y); y += 13;
  const acknowledgement = "FairPool received your pool entry. Joining did not charge you or place a payment hold.";
  y = space(y, Math.max(7 + height(acknowledgement, 90), 26) + 13);
  const noteStart = y;
  caption("ENTRY ACKNOWLEDGEMENT", 18, y);
  const noteEnd = write(acknowledgement, 18, y + 7, 90, 10);
  caption("TOTAL JOINING FEE", 132, y);
  pdf.setFont("helvetica", "bold"); pdf.setFontSize(23); ink(); pdf.text("$0.00", 192, y + 13, { align: "right" });
  caption("USD", 185, y + 20);
  y = Math.max(noteEnd, noteStart + 26) + 13;
  const documentNote = "This is not a payment receipt, an order confirmation or a guaranteed seat. View Orders for purchase amounts, payment status and delivery details.";
  y = space(y, 19 + height(documentNote, 174, 9) + 10);
  rule(y); y += 12;
  caption("ABOUT THIS DOCUMENT", 18, y);
  y = write(documentNote, 18, y + 7, 174, 9) + 10;
  const keepNote = "Your receipt stays available from the pool. The separate signed JSON file contains the verification proof.";
  y = space(y, 7 + height(keepNote, 174, 9) + 8 + height(`/audit/${receipt.payload.pool_id}`, 174, 8));
  caption("KEEP YOUR COPY", 18, y);
  y = write(keepNote, 18, y + 7, 174, 9) + 8;
  write(`/audit/${receipt.payload.pool_id}`, 18, y, 174, 8);
  for (let page = 1; page <= pdf.getNumberOfPages(); page++) {
    pdf.setPage(page); rule(281); pdf.setFont("helvetica", "normal"); pdf.setFontSize(8); muted();
    pdf.text("FairPool | Pool entry acknowledgement", 18, 288);
    pdf.text(`${page} / ${pdf.getNumberOfPages()}`, 192, 288, { align: "right" });
  }
  return pdf;
}
