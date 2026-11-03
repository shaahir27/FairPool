import { useState } from "react";

import { type ApiComponents, accountState, Brand, formatDateTime, Icon, ProductArt } from "../../shared";

type EntryReceipt = ApiComponents["schemas"]["EntryReceipt"];

/** CR-9: the PDF is a readable acknowledgement; the JSON keeps the signed payload unchanged. */
export function EntryReceiptPage({
  receipt,
  poolTitle,
  onBack,
  productDetails,
}: {
  receipt: EntryReceipt;
  poolTitle: string;
  onBack: () => void;
  productDetails?: { condition: string; variant?: string | null; entryStatus: string };
}) {
  const [message, setMessage] = useState("");
  const [downloading, setDownloading] = useState(false);
  const downloadPdf = async () => {
    if (downloading) return;
    setDownloading(true);
    try {
      const { createReceiptPdf } = await import("./receiptPdf");
      const fontResponse = await fetch("/fonts/noto-sans-receipt.ttf");
      if (!fontResponse.ok) throw new Error("Receipt font unavailable");
      const fontBytes = new Uint8Array(await fontResponse.arrayBuffer());
      const fontData = btoa(fontBytes.reduce((text, byte) => text + String.fromCharCode(byte), ""));
      createReceiptPdf(receipt, poolTitle, fontData, fields).save(`fairpool-entry-receipt-${receipt.payload.entry_id}.pdf`);
      setMessage("PDF receipt downloaded. Keep the signed proof for verification.");
    } catch {
      setMessage("Could not download the PDF. Try again, or use Print to save a PDF.");
    } finally { setDownloading(false); }
  };
  const account = accountState();
  const fields: [string, string][] = [
    ["Receipt reference", receipt.payload.entry_id],
    ["Received time", formatDateTime(receipt.payload.received_at)],
    ...(account ? [["Account name", account.display_name]] as [string, string][] : []),
    ...(productDetails ? [["Condition", productDetails.condition.replaceAll("_", " ")],
      ...(productDetails.variant ? [["Variant", productDetails.variant]] : []),
      ["Current entry status", productDetails.entryStatus.replaceAll("_", " ")]] as [string, string][] : []),
    ["Joining fee", "$0.00 USD"],
    ["Purchase payment", "Not recorded by this entry receipt. View Orders for payment details."],
  ];

  const copy = async (label: string, value: string) => {
    try {
      await navigator.clipboard.writeText(value);
      setMessage(`${label} copied.`);
    } catch {
      setMessage(`Could not copy ${label.toLowerCase()}. Select the value to copy it manually.`);
    }
  };

  const download = () => {
    const file = {
      kind: "fairpool.entry_receipt",
      v: 1,
      pool_title: poolTitle,
      // The signed payload, exactly as the API returned it.
      receipt,
      verify: {
        public_keys: "/api/v1/public/keys",
        public_audit: `/audit/${receipt.payload.pool_id}`,
        published_before_seed: "fairness-and-hashing.md: commitments are published first",
      },
    };
    try {
      const blob = new Blob([JSON.stringify(file, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `fairpool-entry-receipt-${receipt.payload.entry_id}.json`;
      document.body.append(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      setMessage("Receipt downloaded as a JSON file. Keep it: it proves this entry.");
    } catch {
      setMessage("Your browser blocked the download. Copy the values above instead.");
    }
  };

  return (
    <section aria-labelledby="entry-receipt-title" className="entry-receipt-page">
      <div className="receipt-page-heading no-print">
        <button type="button" className="shop-back" onClick={onBack}><Icon name="arrow" />Back to the pool</button>
        <h1 id="entry-receipt-title" className="shop-title">Entry receipt</h1>
        <p className="shop-copy">Your pool entry, saved in one place.</p>
      </div>
      <article className="shop-panel receipt-paper" aria-label="Your entry document">
        <header className="receipt-paper-header"><Brand /><div className="receipt-document-title"><p>Entry receipt</p><span>PayPal Sandbox</span></div></header>
        <div className="receipt-document-body">
          <dl className="receipt-metadata">
            {fields.filter(([label]) => !["Condition", "Variant", "Joining fee", "Purchase payment"].includes(label)).map(([label, value]) => <div key={label}>
              <dt>{label}{label === "Receipt reference" ? <button type="button" className="icon-button no-print" aria-label="Copy receipt reference" onClick={() => void copy(label, value)}><Icon name="copy" /></button> : null}</dt>
              <dd>{value}</dd>
            </div>)}
          </dl>
          <section className="receipt-item" aria-label="Pool item">
            <ProductArt title={poolTitle} />
            <div><h2 className="receipt-product">{poolTitle}</h2><p className="shop-copy">{[productDetails?.condition.replaceAll("_", " "), productDetails?.variant].filter(Boolean).join(" · ")}</p><p className="receipt-item-caption">Pool participation · category illustration</p></div>
          </section>
          <section className="receipt-summary" aria-labelledby="receipt-summary-title">
            <div><h2 id="receipt-summary-title">Entry summary</h2><p className="shop-copy">Your entry was received and recorded. Joining did not charge you or place a hold.</p><p className="shop-copy mt-2">This confirms an entry, not a purchase or a guaranteed seat.</p></div>
            <dl><div><dt>Joining fee</dt><dd className="receipt-fee">$0.00 <span>USD</span></dd></div><div><dt>Purchase payment</dt><dd>View Orders for payment details.</dd></div></dl>
          </section>
          <div className="receipt-document-note"><Icon name="shield" /><p>The pool keeps this receipt, so it comes back whenever you open the pool. You can check your entry against the published commitments.</p></div>
        </div>
        <footer className="receipt-document-footer no-print">
          <div className="receipt-download-actions"><button type="button" className="button-primary" disabled={downloading} onClick={() => void downloadPdf()}><Icon name="receipt" />{downloading ? "Preparing PDF…" : "Download PDF"}</button><button type="button" className="button-secondary" onClick={() => window.print()}>Print</button></div>
          <div className="receipt-verification-actions"><a href={`/audit/${receipt.payload.pool_id}`}>Check it on the public audit page</a><button type="button" onClick={download}>Signed proof (JSON)</button></div>
        </footer>
      </article>
      <p className="secondary-copy mt-3 no-print" role="status">{message}</p>
    </section>
  );
}
