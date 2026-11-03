import { useState } from "react";

import { type ApiComponents, formatDateTime, Icon } from "../../shared";

type EntryReceipt = ApiComponents["schemas"]["EntryReceipt"];

/**
 * The entry receipt as a page (T06B05; FR-SL-07).
 *
 * Same values and the same copy affordance as the checkout drawer, because it is the
 * same object: proof that the entry was received, signed by FairPool over the commitment
 * the pool publishes. The drawer lives in the checkout area and the checkout barrel
 * exports three components only (scaffold section 5.8), so the buyer area renders its
 * own copy of this table rather than reaching across.
 *
 * The download is built in the browser from the receipt the server returned (CR-9): the
 * payload is copied as it arrived, because the signature covers that text and a
 * re-serialised timestamp would no longer verify.
 */
export function EntryReceiptPage({
  receipt,
  poolTitle,
  onBack,
}: {
  receipt: EntryReceipt;
  poolTitle: string;
  onBack: () => void;
}) {
  const [message, setMessage] = useState("");
  const fields: [string, string, string][] = [
    ["Commitment", receipt.payload.commitment, "A fingerprint of your entry"],
    ["Entry ID", receipt.payload.entry_id, "Your place in the pool"],
    ["Pool ID", receipt.payload.pool_id, "The pool you joined"],
    ["Received time", formatDateTime(receipt.payload.received_at), "When we got it"],
    ["Salt", receipt.salt_hex, "Keeps your fingerprint private"],
    ["Request hash", receipt.request_hash, "Fingerprint of your request"],
    ["Signature", receipt.signature, "Signed by FairPool"],
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
      URL.revokeObjectURL(url);
      setMessage("Receipt downloaded as a JSON file. Keep it: it proves this entry.");
    } catch {
      setMessage("Your browser blocked the download. Copy the values above instead.");
    }
  };

  return (
    <section aria-labelledby="entry-receipt-title">
      <div className="shop-heading flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <h1 id="entry-receipt-title" className="font-display text-[32px] leading-[1.12] tracking-[-.04em]">
            Entry receipt
          </h1>
          <p className="shop-copy mt-2">
            {poolTitle} · received {formatDateTime(receipt.payload.received_at)}
          </p>
        </div>
        <div className="no-print order-page-actions">
          <button type="button" className="shop-quiet-button" onClick={download}>
            <Icon name="receipt" />
            Download receipt
          </button>
          <button type="button" className="shop-quiet-button" onClick={() => window.print()}>
            <Icon name="box" />
            Print
          </button>
        </div>
      </div>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_320px]">
        <section className="shop-panel">
          <div className="panel-band">
            <h2>What this proves</h2>
          </div>
          <div className="shop-panel-pad">
            <p className="shop-copy">
              Your entry was received and recorded. Nothing has been charged and no hold placed: a
              merchant still has to win the lot, and you approve your own payment.
            </p>
            <dl className="receipt-fields">
              {fields.map(([label, value, help]) => (
                <div className="receipt-field" key={label}>
                  <dt>
                    {label}
                    <button
                      type="button"
                      className="icon-button no-print"
                      aria-label={`Copy ${label.toLowerCase()}`}
                      onClick={() => void copy(label, value)}
                    >
                      <Icon name="copy" />
                    </button>
                  </dt>
                  <dd>
                    {value}
                    <span className="receipt-help">{help}</span>
                  </dd>
                </div>
              ))}
            </dl>
            <p className="secondary-copy mt-3" role="status">
              {message}
            </p>
          </div>
        </section>

        <aside className="grid content-start gap-5">
          <section className="shop-panel order-info">
            <h2>Keep it, verify it</h2>
            <p className="shop-copy mt-2">
              The pool keeps this receipt, so it comes back whenever you open the pool — on any
              device you sign in from. Download a copy to keep, and check it against the published
              commitments.
            </p>
            <a
              className="mt-4 inline-block text-sm font-semibold underline underline-offset-4"
              href={`/audit/${receipt.payload.pool_id}`}
            >
              Check it on the public audit page
            </a>
          </section>
          <section className="order-help">
            <h2>What happens next</h2>
            <p>
              The pool closes its entry window, publishes the commitments, and only then draws the
              order. If a merchant wins your lot and a seat comes to you, you get your own offer to
              approve.
            </p>
            <button type="button" className="signup-back mt-4 no-print" onClick={onBack}>
              Back to the pool
            </button>
          </section>
        </aside>
      </div>
    </section>
  );
}
