import { type FormEvent, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import {
  api,
  type ApiComponents,
  FieldError,
  formatCents,
  Notice,
  StatusPill,
} from "../../shared";
import { failureEnvelope, productName } from "../lib";
import { BidFields } from "./BidFields";

type LotSummary = ApiComponents["schemas"]["MerchantLotSummary"];
type Ambiguity = ApiComponents["schemas"]["QuoteAmbiguity"];

type QuoteNotice = {
  kind: "info" | "warn" | "error";
  code?: string;
  message: string;
};

type Reviewed = {
  structured: Record<string, unknown>;
  idempotencyKey: string;
};

type SavedBid = {
  hash: string;
  status: string;
  revision: number;
  confirmedStatus: string | null;
};

type Tier = { minQty: number; priceCents: number };

function recordValue(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function textValue(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function intValue(value: unknown): number | null {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0 ? value : null;
}

function stringsValue(value: unknown): string[] | null {
  if (!Array.isArray(value)) return null;
  const rows = value.filter((part): part is string => typeof part === "string" && part.trim().length > 0);
  return rows.length > 0 ? rows : null;
}

function tiersOf(value: unknown): Tier[] {
  if (!Array.isArray(value)) return [];
  const tiers: Tier[] = [];
  for (const entry of value) {
    const row = recordValue(entry);
    if (!row) continue;
    const minQty = intValue(row.min_qty);
    const priceCents = intValue(row.item_price_cents);
    if (minQty !== null && priceCents !== null) tiers.push({ minQty, priceCents });
  }
  return tiers;
}

/** Lot requirements prefill the manual form; the merchant must enter a price. */
function templateFor(lot: LotSummary): Record<string, unknown> {
  return {
      v: 1,
      product_key: lot.product_key,
      condition: lot.condition,
      bundle_contents: [],
      capacity: lot.seats,
      target_quantity: lot.min_seats,
      moq: lot.min_seats,
      tiers: [{ min_qty: 1, item_price_cents: null }],
      shipping_cents_by_zone: { [lot.zone_id]: 0 },
      tax: { mode: "INCLUDED" },
      delivery: { sla_days: lot.delivery_sla_days },
      returns: { days: lot.min_return_days },
      valid_until: lot.bid_close_at,
      evidence: { note: "" },
  };
}

function newIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `bid-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

function Summary({ structured, fallbackKey }: { structured: Record<string, unknown>; fallbackKey: string }) {
  const bundle = stringsValue(structured.bundle_contents);
  const capacity = intValue(structured.capacity);
  const target = intValue(structured.target_quantity);
  const moq = intValue(structured.moq);
  const delivery = recordValue(structured.delivery);
  const returns = recordValue(structured.returns);
  const slaDays = delivery ? intValue(delivery.sla_days) : null;
  const returnDays = returns ? intValue(returns.days) : null;
  const tiers = tiersOf(structured.tiers);
  const quantity = [
    capacity !== null ? `capacity ${capacity}` : null,
    target !== null ? `target ${target}` : null,
    moq !== null ? `minimum ${moq}` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <dl className="merchant-review-rows">
      <div>
        <dt>Product</dt>
        <dd>
          {textValue(structured.product_key) ?? fallbackKey}
          {textValue(structured.condition) ? ` · ${textValue(structured.condition)}` : null}
        </dd>
      </div>
      <div>
        <dt>Bundle</dt>
        <dd>{bundle ? bundle.join(", ") : "Not stated in the bid"}</dd>
      </div>
      <div>
        <dt>Quantity</dt>
        <dd>{quantity || "Not stated in the bid"}</dd>
      </div>
      <div>
        <dt>Price tiers</dt>
        <dd>
          {tiers.length > 0 ? (
            <ul className="merchant-tier-list" aria-label="Price tiers">
              {tiers.map((tier) => (
                <li key={`${tier.minQty}-${tier.priceCents}`}>
                  <span>{tier.minQty}+ at</span> <strong>{formatCents(tier.priceCents)}</strong>
                </li>
              ))}
            </ul>
          ) : (
            "No tiers stated in the bid"
          )}
        </dd>
      </div>
      <div><dt>Price includes</dt><dd>Shipping and tax</dd></div>
      {intValue(structured.total_capacity) !== null ? <div><dt>Shared inventory capacity</dt><dd>{intValue(structured.total_capacity)}</dd></div> : null}
      <div>
        <dt>Delivery</dt>
        <dd>{slaDays !== null ? `within ${slaDays} days` : "Not stated in the bid"}</dd>
      </div>
      <div>
        <dt>Returns</dt>
        <dd>{returnDays !== null ? `${returnDays} days` : "Not stated in the bid"}</dd>
      </div>
      <div>
        <dt>Valid until</dt>
        <dd>{textValue(structured.valid_until) ?? "Not stated in the bid"}</dd>
      </div>
      <div><dt>Supply evidence</dt><dd>{textValue(recordValue(structured.evidence)?.note) ?? "Not stated in the bid"}</dd></div>
      {textValue(recordValue(structured.evidence)?.url) ? <div><dt>Evidence link</dt><dd className="break-all">{textValue(recordValue(structured.evidence)?.url)}</dd></div> : null}
    </dl>
  );
}

/**
 * DEP-2: the parser proposes, the merchant confirms. The PUT is not sent until
 * the merchant has reviewed the fields and pressed Save and confirm bid.
 */
export function BidComposer({ lot }: { lot: LotSummary }) {
  const [quoteText, setQuoteText] = useState("");
  const [fields, setFields] = useState<Record<string, unknown>>(() => templateFor(lot));
  const [formVersion, setFormVersion] = useState(0);
  const [notes, setNotes] = useState("");
  const [parsing, setParsing] = useState(false);
  const [quoteNotice, setQuoteNotice] = useState<QuoteNotice | null>(null);
  const [ambiguities, setAmbiguities] = useState<Ambiguity[]>([]);
  const [formProblem, setFormProblem] = useState("");
  const [reviewed, setReviewed] = useState<Reviewed | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveProblem, setSaveProblem] = useState<{ code: string; message: string } | null>(null);
  const [saved, setSaved] = useState<SavedBid | null>(null);
  const [confirmProblem, setConfirmProblem] = useState<{ code: string; message: string } | null>(null);
  const [stage, setStage] = useState<"edit" | "review" | "saved">("edit");
  const composerHeading = useRef<HTMLHeadingElement>(null);
  const stageHeading = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    // The composer appears below the lot when chosen; keyboard users land on it.
    composerHeading.current?.focus();
  }, []);

  useEffect(() => {
    // The edit form unmounts on review and save; move focus so a keyboard user
    // lands on the card that replaced it.
    if (stage !== "edit") stageHeading.current?.focus();
  }, [stage]);

  async function parseQuote() {
    const text = quoteText.trim();
    if (!text || parsing) return;
    setParsing(true);
    setQuoteNotice(null);
    setAmbiguities([]);
    try {
      const { data, error: failure } = await api.POST("/api/v1/merchant/lots/{lot_id}/quote", {
        params: { path: { lot_id: lot.lot_id } },
        body: { quote_text: text },
      });
      if (failure || !data) {
        const envelope = failureEnvelope(failure);
        setQuoteNotice(
          envelope.code === "FEATURE_DISABLED"
            ? {
                kind: "warn",
                code: envelope.code,
                message: "Quote parsing is unavailable. Fill in the bid fields below.",
              }
            : { kind: "error", code: envelope.code, message: envelope.message },
        );
        return;
      }
      setFields({ ...recordValue(data.proposed_fields), v: 1 });
      setFormVersion((version) => version + 1);
      setAmbiguities(data.ambiguities ?? []);
      setQuoteNotice({
        kind: "info",
        message: "Quote parsed into the fields below. Check every value before review.",
      });
    } catch {
      setQuoteNotice({
        kind: "error",
        code: "REQUEST_FAILED",
        message: "Check your connection and parse the quote again.",
      });
    } finally {
      setParsing(false);
    }
  }

  function reviewBid(event: FormEvent) {
    event.preventDefault();
    setFormProblem("");
    const structured = { ...fields };
    if (structured.total_capacity === null) delete structured.total_capacity;
    if (structured.shipping_cents_by_zone === null) delete structured.shipping_cents_by_zone;
    if (!Array.isArray(fields.tiers) || fields.tiers.length === 0) {
      setFormProblem("Add at least one delivered price tier before review.");
      return;
    }
    if (recordValue(fields.tax)?.mode !== "INCLUDED" || Object.values(recordValue(fields.shipping_cents_by_zone) ?? {}).some((cost) => cost !== 0)) {
      setFormProblem("Your delivered prices must include shipping and tax. Confirm the included-price terms before review.");
      return;
    }
    if (fields.tiers.some((tier) => intValue(recordValue(tier)?.item_price_cents) === null)) {
      setFormProblem("Enter a valid USD price with no more than two decimal places for every tier.");
      return;
    }
    setReviewed({ structured, idempotencyKey: newIdempotencyKey() });
    setSaved(null);
    setSaveProblem(null);
    setConfirmProblem(null);
    setStage("review");
  }

  async function saveBid(event: FormEvent) {
    event.preventDefault();
    if (!reviewed || saving) return;
    setSaving(true);
    setSaveProblem(null);
    setConfirmProblem(null);
    try {
      const { data, error: failure } = await api.PUT("/api/v1/merchant/lots/{lot_id}/bid", {
        params: { path: { lot_id: lot.lot_id } },
        headers: { "Idempotency-Key": reviewed.idempotencyKey },
        body: {
          structured: reviewed.structured,
          quote_text: quoteText.trim() ? quoteText.trim() : null,
          notes: notes.trim() ? notes.trim() : null,
        },
      });
      if (failure || !data) {
        setSaveProblem(failureEnvelope(failure));
        return;
      }
      const row: SavedBid = {
        hash: data.receipt.hash,
        status: data.status,
        revision: data.revision,
        confirmedStatus: null,
      };
      setSaved(row);
      // The receipt exists even if the confirm below fails; keep it visible.
      try {
        const confirmed = await api.POST("/api/v1/merchant/bids/{bid_id}/confirm", {
          params: { path: { bid_id: data.bid_id } },
          headers: { "Idempotency-Key": `${reviewed.idempotencyKey}:confirm` },
          body: { revision: data.revision },
        });
        if (confirmed.error || !confirmed.data) {
          setConfirmProblem(failureEnvelope(confirmed.error));
        } else {
          setSaved({ ...row, confirmedStatus: confirmed.data.status });
        }
      } catch {
        setConfirmProblem({
          code: "REQUEST_FAILED",
          message: "The revision is saved, but the confirmation did not reach the server.",
        });
      }
      setStage("saved");
    } catch {
      setSaveProblem({
        code: "REQUEST_FAILED",
        message: "Check your connection. Nothing is saved until the server answers.",
      });
    } finally {
      setSaving(false);
    }
  }

  function startOver() {
    setQuoteText("");
    setFields(templateFor(lot));
    setFormVersion((version) => version + 1);
    setNotes("");
    setAmbiguities([]);
    setQuoteNotice(null);
    setFormProblem("");
    setReviewed(null);
    setSaved(null);
    setSaveProblem(null);
    setConfirmProblem(null);
    setStage("edit");
  }

  return (
    <section className="shop-panel merchant-composer" aria-labelledby="bid-composer-title">
      <div className="panel-band">
        <h2 id="bid-composer-title" ref={composerHeading} tabIndex={-1}>
          Prepare a sealed bid
        </h2>
        <p className="shop-copy mt-1">
          {productName(lot.product_key)} · {lot.zone_id} · {lot.seats} seats · minimum{" "}
          {lot.min_seats}
        </p>
      </div>
      <div className="shop-panel-pad">
        {stage === "edit" ? (
          <form onSubmit={reviewBid}>
            <div className="merchant-composer-grid bid-composer-workspace">
              <details className="bid-quote-import">
                <summary>Import an existing quote (optional)</summary>
                <label className="merchant-field" htmlFor="bid-quote">
                  Paste your quote
                </label>
                <textarea
                  id="bid-quote"
                  className="form-input merchant-textarea"
                  rows={6}
                  value={quoteText}
                  maxLength={4000}
                  placeholder="Paste the seller's quote. The parser proposes fields; you confirm them."
                  onChange={(event) => setQuoteText(event.target.value)}
                />
                <div className="merchant-actions">
                  <button
                    type="button"
                    className="button-secondary"
                    disabled={!quoteText.trim() || parsing}
                    onClick={() => void parseQuote()}
                  >
                    {parsing ? "Parsing…" : "Parse quote"}
                  </button>
                </div>
                {quoteNotice ? (
                  <div className="mt-4">
                    <Notice kind={quoteNotice.kind} {...(quoteNotice.code ? { code: quoteNotice.code } : {})}>
                      {quoteNotice.message}
                    </Notice>
                  </div>
                ) : null}
                {ambiguities.length > 0 ? (
                  <div className="mt-4">
                    <h3 className="merchant-subheading">Open questions from the quote</h3>
                    <ul className="merchant-ambiguities">
                      {ambiguities.map((ambiguity) => (
                        <li key={`${ambiguity.field}-${ambiguity.question}`}>
                          <strong>{ambiguity.field.replaceAll("_", " ")}</strong>
                          <p>{ambiguity.question}</p>
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
                <div className="merchant-help">
                  The parser never qualifies a bid. A blocking flag withholds it until you
                  save a corrected revision.
                </div>
                <label className="merchant-field mt-4" htmlFor="bid-notes">
                  Notes for the record (optional)
                </label>
                <textarea
                  id="bid-notes"
                  className="form-input merchant-textarea"
                  rows={3}
                  value={notes}
                  maxLength={2000}
                  onChange={(event) => setNotes(event.target.value)}
                />
              </details>
              <div>
                <BidFields key={formVersion} value={fields} onChange={setFields} />
                {formProblem ? <FieldError>{formProblem}</FieldError> : null}
                <div className="merchant-actions">
                  <button type="submit" className="button-primary">
                    Review bid
                  </button>
                </div>
              </div>
            </div>
          </form>
        ) : null}

        {stage === "review" && reviewed ? (
          <section aria-labelledby="bid-confirm-title" className="merchant-review">
            <h3 id="bid-confirm-title" ref={stageHeading} tabIndex={-1}>
              Confirm this bid
            </h3>
            <p className="shop-copy mt-1">
              Nothing is saved until you choose Save and confirm bid.
            </p>
            <Summary structured={reviewed.structured} fallbackKey={lot.product_key} />
            {saveProblem ? (
              <div className="mt-4">
                <Notice kind="error" code={saveProblem.code}>
                  {saveProblem.message}
                </Notice>
              </div>
            ) : null}
            <form onSubmit={(event) => void saveBid(event)}>
              <div className="merchant-actions">
                <button type="submit" className="button-primary" disabled={saving}>
                  {saving ? "Saving and confirming…" : "Save and confirm bid"}
                </button>
                <button
                  type="button"
                  className="shop-quiet-button"
                  disabled={saving}
                  onClick={() => setStage("edit")}
                >
                  Back to edit
                </button>
              </div>
            </form>
          </section>
        ) : null}

        {stage === "saved" && saved ? (
          <section aria-labelledby="bid-saved-title" className="merchant-result">
            <h3 id="bid-saved-title" ref={stageHeading} tabIndex={-1}>
              {saved.confirmedStatus ? "Bid confirmed" : "Bid saved, not confirmed"}
            </h3>
            <p className="shop-copy mt-1">
              {saved.confirmedStatus
                ? "The sealed revision is confirmed. The receipt below identifies it."
                : "The revision has a receipt, but its confirmation did not complete. Check Active Bids before relying on this bid."}
            </p>
            <div className="merchant-result-status">
              <StatusPill status={saved.confirmedStatus ?? saved.status} />
              <span className="shop-copy">Revision {saved.revision}</span>
            </div>
            {confirmProblem ? (
              <div className="mt-4">
                <Notice kind="error" code={confirmProblem.code}>
                  {confirmProblem.message}
                </Notice>
              </div>
            ) : null}
            <details className="merchant-proof"><summary>Sealed bid receipt</summary>
            <p className="merchant-label">Receipt hash</p>
            <code className="merchant-hash">{saved.hash}</code>
            <p className="merchant-help">
              Keep this hash. It identifies the sealed revision and is not shown again in
              this form.
            </p>
            </details>
            <div className="merchant-actions">
              <Link className="button-secondary" to="/merchant/bids">
                Open Active Bids
              </Link>
              <button type="button" className="shop-quiet-button" onClick={startOver}>
                Prepare another bid
              </button>
            </div>
          </section>
        ) : null}
      </div>
    </section>
  );
}
