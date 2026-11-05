import { useEffect, useState } from "react";
import { dollarsToCents } from "./money";

type Fields = Record<string, unknown>;
function object(value: unknown): Fields {
  return typeof value === "object" && value !== null && !Array.isArray(value) ? value as Fields : {};
}
function text(value: unknown): string { return typeof value === "string" ? value : ""; }
function integer(value: unknown): number | "" { return typeof value === "number" ? value : ""; }

function PriceInput({ value, index, onChange }: { value: unknown; index: number; onChange: (value: number | null) => void }) {
  const [draft, setDraft] = useState(() => typeof value === "number"
    ? `${Math.floor(value / 100)}.${String(value % 100).padStart(2, "0")}` : "");
  useEffect(() => {
    if (dollarsToCents(draft) !== value) setDraft(typeof value === "number"
      ? `${Math.floor(value / 100)}.${String(value % 100).padStart(2, "0")}` : "");
  }, [value, draft]);
  return <label className="bid-field">Delivered price, tier {index + 1} (USD)
    <input className="form-input" inputMode="decimal" required pattern="[0-9]+([.][0-9]{0,2})?" value={draft}
      onChange={(event) => { setDraft(event.target.value); onChange(dollarsToCents(event.target.value)); }} />
  </label>;
}

export function BidFields({ value, onChange }: { value: Fields; onChange: (value: Fields) => void }) {
  const tiers = Array.isArray(value.tiers) ? value.tiers.map(object) : [];
  const delivery = object(value.delivery);
  const returns = object(value.returns);
  const evidence = object(value.evidence);
  const shipping = object(value.shipping_cents_by_zone);
  const validUntil = new Date(text(value.valid_until));
  const dateTime = Number.isNaN(validUntil.getTime()) ? "" : validUntil.toISOString().slice(0, 19);
  const included = object(value.tax).mode === "INCLUDED" && Object.values(shipping).every((cost) => cost === 0);
  const update = (field: string, next: unknown) => onChange({ ...value, [field]: next });
  const updateTier = (index: number, field: string, next: unknown) => update("tiers",
    tiers.map((tier, row) => row === index ? { ...tier, [field]: next } : tier));
  const numberField = (label: string, field: string, optional = false) => <label className="bid-field" key={field}>{label}
    <input className="form-input" type="number" min="1" step="1" required={!optional} value={integer(value[field])}
      onChange={(event) => {
        if (!event.target.value && optional) {
          const next = { ...value }; delete next[field]; onChange(next);
        } else update(field, event.target.value ? Number(event.target.value) : null);
      }} />
  </label>;
  return <div className="bid-fields">
    <fieldset className="bid-fieldset"><legend>Product and supply</legend>
      <p className="merchant-help">Check the product and quantities you can supply for this lot.</p>
      <div className="bid-field-pair">
        <label className="bid-field">Product reference<input className="form-input" required value={text(value.product_key)} onChange={(event) => update("product_key", event.target.value)} /></label>
        <label className="bid-field">Condition<input className="form-input" required value={text(value.condition)} onChange={(event) => update("condition", event.target.value)} /></label>
      </div>
      <label className="bid-field">Included items
        <textarea className="form-input merchant-textarea" rows={3} required aria-label="Included items" placeholder="One item per line"
          value={Array.isArray(value.bundle_contents) ? value.bundle_contents.join("\n") : ""}
          onChange={(event) => update("bundle_contents", event.target.value.split("\n"))} />
        <span className="merchant-help">List the product, accessories and other items included in your price.</span>
      </label>
      <div className="bid-field-pair">{numberField("Available quantity", "capacity")}{numberField("Target quantity", "target_quantity")}{numberField("Minimum order quantity", "moq")}{numberField("Shared inventory capacity (optional)", "total_capacity", true)}</div>
    </fieldset>
    <fieldset className="bid-fieldset"><legend>Delivered prices</legend>
      <p className="merchant-help">USD per item, including shipping and tax. Add up to three quantity tiers.</p>
      {!included ? <div className="bid-pricing-correction"><p>This proposal does not include all shipping and tax. Update your delivered prices below before confirming the included-price terms.</p>
        <button type="button" className="button-secondary" onClick={() => onChange({ ...value, tax: {mode: "INCLUDED"}, shipping_cents_by_zone: Object.fromEntries(Object.keys(shipping).map((zone) => [zone, 0])) })}>Use shipping and tax included</button>
      </div> : null}
      {tiers.map((tier, index) => <div className="bid-tier" key={index}>
        <div className="bid-field-pair">
          <label className="bid-field">Minimum quantity, tier {index + 1}<input className="form-input" type="number" min="1" step="1" required value={integer(tier.min_qty)} onChange={(event) => updateTier(index, "min_qty", event.target.value ? Number(event.target.value) : null)} /></label>
          <PriceInput value={tier.item_price_cents} index={index} onChange={(next) => updateTier(index, "item_price_cents", next)} />
        </div>
        {tiers.length > 1 ? <button type="button" className="merchant-link" onClick={() => update("tiers", tiers.filter((_, row) => row !== index))}>Remove tier {index + 1}</button> : null}
      </div>)}
      {tiers.length < 3 ? <button type="button" className="button-secondary" onClick={() => update("tiers", [...tiers, { min_qty: null, item_price_cents: null }])}>Add price tier</button> : null}
      <p className="merchant-help">Use increasing minimum quantities and the same or a lower price at each tier. The server checks your offer.</p>
    </fieldset>
    <fieldset className="bid-fieldset"><legend>Delivery and returns</legend>
      <div className="bid-field-pair">
        <label className="bid-field">Delivery within (days)<input className="form-input" type="number" min="1" step="1" required value={integer(delivery.sla_days)} onChange={(event) => update("delivery", { ...delivery, sla_days: event.target.value ? Number(event.target.value) : null })} /></label>
        <label className="bid-field">Return window (days)<input className="form-input" type="number" min="0" step="1" required value={integer(returns.days)} onChange={(event) => update("returns", { ...returns, days: event.target.value ? Number(event.target.value) : null })} /></label>
      </div>
      <label className="bid-field">Offer valid until (UTC)<input className="form-input" type="datetime-local" step="1" aria-label="Offer valid until (UTC)" required value={dateTime} onChange={(event) => update("valid_until", event.target.value ? `${event.target.value}${event.target.value.length === 16 ? ":00" : ""}Z` : null)} /><span className="merchant-help">Choose the date and time in UTC.</span></label>
    </fieldset>
    <fieldset className="bid-fieldset"><legend>Supply evidence</legend>
      <label className="bid-field">Supply evidence<textarea className="form-input merchant-textarea" rows={3} required aria-label="Supply evidence" value={text(evidence.note)} onChange={(event) => update("evidence", { ...evidence, note: event.target.value })} /><span className="merchant-help">Describe the stock or supply commitment behind this offer.</span></label>
      <label className="bid-field">Evidence link (optional)<input className="form-input" type="url" value={text(evidence.url)} onChange={(event) => {
        const next = { ...evidence }; if (event.target.value) next.url = event.target.value; else delete next.url;
        update("evidence", next);
      }} /></label>
    </fieldset>
  </div>;
}
