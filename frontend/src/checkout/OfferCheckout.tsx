import { type FormEvent, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, type ApiComponents, formatCents, Icon, Notice, StatusPill, startRouteTransition, useCountdown } from "../shared";

type Offer = ApiComponents["schemas"]["OfferResponse"];
const ADDRESS_FIELDS = [
  { name: "name", label: "Name", autoComplete: "name", required: true },
  { name: "line1", label: "Address line 1", autoComplete: "address-line1", required: true },
  { name: "line2", label: "Address line 2 (optional)", autoComplete: "address-line2", required: false },
  { name: "city", label: "City", autoComplete: "address-level2", required: true },
  { name: "region", label: "Region", autoComplete: "address-level1", required: true },
  { name: "postal_code", label: "Postal code", autoComplete: "postal-code", required: true },
  { name: "country_code", label: "Country code", autoComplete: "country", required: true },
] as const;
type AddressField = (typeof ADDRESS_FIELDS)[number]["name"];
const EMPTY_ADDRESS: Record<AddressField, string> = { name: "", line1: "", line2: "", city: "", region: "", postal_code: "", country_code: "US" };

export function OfferCheckout({ buyerOrderId }: { buyerOrderId: string }) {
  const [offer, setOffer] = useState<Offer | null>(null);
  const [error, setError] = useState<{ code: string; message: string } | null>(null);
  useEffect(() => {
    let live = true;
    setOffer(null);
    setError(null);
    void api.GET("/api/v1/offers/{buyer_order_id}", { params: { path: { buyer_order_id: buyerOrderId } } })
      .then(({ data, error: failure }) => {
        if (!live) return;
        if (failure || !data) setError(codeOf(failure));
        else setOffer(data);
      }).catch(() => { if (live) setError({ code: "REQUEST_FAILED", message: "Check your connection and reload this offer." }); });
    return () => { live = false; };
  }, [buyerOrderId]);
  if (error) return <Notice kind="error" code={error.code}>{error.message}</Notice>;
  if (!offer) return <section className="panel" role="status" aria-label="Loading offer" aria-busy="true"><p className="meta-label">Loading offer</p><div className="skeleton mt-5 h-10 w-2/3" /><div className="skeleton mt-4 h-40" /><div className="skeleton mt-4 h-12" /></section>;
  return <OfferDetails key={buyerOrderId} offer={offer} />;
}

function OfferDetails({ offer }: { offer: Offer }) {
  const navigate = useNavigate();
  const [address, setAddress] = useState(EMPTY_ADDRESS);
  const [busy, setBusy] = useState<"continue" | "decline" | null>(null);
  const [error, setError] = useState<{ code: string; message: string } | null>(null);
  // Older responses lack server_now. Capture a stable display-only sample once.
  const [clockSample] = useState(() => offer.server_now ?? new Date().toISOString());
  const countdown = useCountdown(offer.offer_expires_at, clockSample, offer.offer_started_at);
  const orderPath = `/orders/${offer.buyer_order_id}`;
  const goToOrder = () => startRouteTransition(() => navigate(orderPath), `/offers/${offer.buyer_order_id}`, orderPath);
  const decline = async () => {
    if (busy) return;
    setBusy("decline"); setError(null);
    try {
      const { error: failure } = await api.POST("/api/v1/offers/{buyer_order_id}/decline", { params: { path: { buyer_order_id: offer.buyer_order_id } } });
      if (failure) { setError(codeOf(failure)); return; }
      goToOrder();
    } catch { setError({ code: "REQUEST_FAILED", message: "Check your connection and try again." }); }
    finally { setBusy(null); }
  };
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (busy || countdown.expired) return;
    setBusy("continue"); setError(null);
    // The browser's `required` only helps when the inputs are inside the form;
    // check here so an incomplete address never reaches the API.
    const missingFields = ADDRESS_FIELDS.filter(
      (field) => field.required && !address[field.name].trim(),
    ).map((field) => field.label);
    if (missingFields.length > 0) {
      setBusy(null);
      setError({ code: "VALIDATION_ERROR", message: `Add ${missingFields.join(", ")}.` });
      return;
    }
    try {
      const { data, error: failure } = await api.POST("/api/v1/offers/{buyer_order_id}/continue", {
        params: { path: { buyer_order_id: offer.buyer_order_id } }, body: { shipping: address },
      });
      if (failure || !data) { setError(codeOf(failure)); return; }
      // I14, INT-7: never log the approval URL; no amount leaves the browser.
      window.location.assign(data.approve_url);
    } catch { setError({ code: "REQUEST_FAILED", message: "Check your connection and try again." }); }
    finally { setBusy(null); }
  };
  const terminal = offer.status !== "OFFERED" && offer.status !== "ORDER_CREATED";
  if (terminal || countdown.expired) {
    const expired = offer.status === "EXPIRED" || (!terminal && countdown.expired);
    return <section className="panel terminal-offer">
      <Icon name={expired ? "clock" : "receipt"} />
      <StatusPill status={expired ? "EXPIRED" : offer.status} />
      <h1>{expired ? "This offer can no longer be approved." : offer.status === "DECLINED" ? "Offer declined" : "Your offer has moved on"}</h1>
      <p className="secondary-copy mt-3">{expired ? "Your approval window has ended. Check your order for the latest status." : "Check your order for the latest payment and lot status."}</p>
      <Link to={orderPath} className="button-secondary mt-6">View order status <Icon name="arrow" /></Link>
    </section>;
  }
  const unused = offer.totals.cap_cents - offer.totals.total_cents;
  return <div className="shop-checkout">
    <Link className="shop-back" to={offer.pool_id ? `/pools/${offer.pool_id}` : "/my-pools"}><Icon name="arrow" />Back to your pool</Link>
    <div className="shop-heading">
      <h1 className="shop-title">Checkout</h1>
      <p className="shop-copy">Your group price is ready. Add your delivery details, then continue to PayPal.</p>
      <ol className="checkout-steps" aria-label="Checkout progress">
        <li aria-current="step"><span className="step-number">1</span>Delivery</li><li aria-hidden="true"><Icon name="chevron" /></li>
        <li><span className="step-number">2</span>PayPal</li><li aria-hidden="true"><Icon name="chevron" /></li>
        <li><span className="step-number">3</span>Confirmation</li>
      </ol>
    </div>
    {offer.notices.fallback ? <p className="preview-disclosure"><Icon name="info" /><span><strong>Sandbox fallback. </strong>{offer.notices.fallback}</span></p> : null}
    {error ? <div className="mb-4"><Notice kind="error" code={error.code}>{error.message}</Notice></div> : null}
    <form id="checkout-form" className="shop-checkout-grid" onSubmit={(event) => void submit(event)}>
      <div className="shop-checkout-main">
        <section className="shop-panel shop-panel-pad" aria-labelledby="delivery-heading">
          <div className="shop-section-heading"><Icon name="truck" /><h2 id="delivery-heading">Delivery details</h2></div>
          <p className="shop-copy">Where should your order be sent?</p>
          <div className="shop-address-fields">
            {ADDRESS_FIELDS.map((field) => field.name === "line2" ? <details key={field.name} className="optional-address"><summary><span aria-hidden="true">+</span> Add apartment, suite or floor</summary><label>Address line 2 (optional)<input name="line2" autoComplete="address-line2" className="form-input" value={address.line2} maxLength={200} onChange={(event) => setAddress((previous) => ({ ...previous, line2: event.target.value }))} /></label></details> : <label key={field.name} className={["name", "line1"].includes(field.name) ? "address-full" : field.name === "country_code" ? "country-field" : ""}>
              {field.label}<input name={field.name} autoComplete={field.autoComplete} className="form-input" value={address[field.name]} required={field.required}
                maxLength={field.name === "country_code" ? 2 : field.name === "postal_code" ? 20 : 200}
                pattern={field.name === "country_code" ? "[A-Za-z]{2}" : undefined}
                onChange={(event) => setAddress((previous) => ({ ...previous, [field.name]: event.target.value }))} />
            </label>)}
          </div>
        </section>
        <section className="shop-panel shop-panel-pad" aria-labelledby="payment-heading">
          <div className="shop-section-heading"><Icon name="wallet" /><h2 id="payment-heading">Payment</h2></div>
          <div className="payment-choice"><span className="paypal-word">PayPal</span><p className="shop-copy">Continue on PayPal to review your payment.</p><Icon name="lock" /></div>
          <p className="payment-description">{offer.notices.hold}</p>
          <div className="checkout-actions"><button type="submit" disabled={busy !== null || countdown.expired} className="button-primary w-full">{busy === "continue" ? "Opening PayPal…" : <>Continue to PayPal <Icon name="arrow" /></>}</button></div>
          <p className="checkout-fineprint"><Icon name="lock" />Your address is stored encrypted.</p>
          <button type="button" disabled={busy !== null} onClick={() => void decline()} className="decline-link">{busy === "decline" ? "Declining…" : "Decline this offer"}</button>
        </section>
      </div>
      <aside className="shop-panel shop-summary" aria-label="Order summary">
        <div className="shop-summary-header"><h2>Order summary</h2><span className="item-count">1 item</span></div>
        <div className={`reservation-note ${countdown.urgent ? "is-urgent" : ""}`}><span><Icon name="clock" />Offer expires in</span><time>{countdown.label}</time></div>
        <div className="shop-summary-body">
          <div className="shop-product-row"><ProductArt title={offer.product.title} small /><div><h2>{offer.product.title}</h2><p>{[offer.product.variant, offer.product.condition].filter(Boolean).join(" · ")}</p><p>Sold by {offer.merchant.display_name}</p><p>Quantity: 1</p></div></div>
          <dl className="price-rows"><Price label="Item" cents={offer.totals.item_cents} /><Price label="Shipping" cents={offer.totals.shipping_cents} /><Price label="Tax" cents={offer.totals.tax_cents} /></dl>
          <div className="shop-summary-total"><strong>Total <span className="text-xs font-normal text-muted">USD</span></strong><strong>{formatCents(offer.totals.total_cents)}</strong></div>
          <div className="budget-note"><Icon name="check" /><span>Your maximum is <strong>{formatCents(offer.totals.cap_cents)}</strong>. {unused >= 0 ? `This total is ${formatCents(unused)} within your limit.` : "Review the final total before continuing."}</span></div>
        </div>
        <div className="summary-terms"><div><Icon name="truck" /><span>Delivery within {offer.terms.delivery_sla_days} days</span></div><div><Icon name="returns" /><span>{offer.terms.returns_days}-day return terms</span></div><div><Icon name="box" /><span>{offer.product.bundle_contents.join(", ")}</span></div></div>
        <details className="shop-disclosure"><summary>How your group price works <Icon name="down" /></summary><p>Merchants submitted sealed bids for this lot. The lowest qualifying price won, and your total fits your confirmed limit.</p><p>{offer.notices.lots_may_differ}</p>{offer.pool_id ? <Link to={`/audit/${offer.pool_id}`}>View this pool’s published rules</Link> : null}</details>
      </aside>
    </form>
  </div>;
}

export function ProductArt({ title, small = false }: { title: string; small?: boolean }) {
  return <div className={`product-art ${small ? "product-art-small" : ""}`} aria-hidden="true">
    {/monitor/i.test(title) ? <svg viewBox="0 0 160 130" fill="none"><rect x="15" y="12" width="130" height="84" rx="7" fill="rgb(var(--color-ink))" stroke="rgb(var(--color-canvas) / .7)" strokeWidth="3" /><rect x="22" y="19" width="116" height="70" rx="3" fill="rgb(var(--color-accent-soft))" /><path d="M22 69Q48 48 76 62T138 56V89H22Z" fill="rgb(var(--color-accent))" opacity=".8" /><path d="M22 76Q50 56 77 70T138 65V89H22Z" fill="rgb(var(--color-muted))" /><path d="M80 97v21 M57 119h46" stroke="rgb(var(--color-canvas))" strokeWidth="4" strokeLinecap="round" /></svg> : <Icon name="box" />}
  </div>;
}
function Price({ label, cents }: { label: string; cents: number }) { return <div><dt>{label}</dt><dd>{formatCents(cents)}</dd></div>; }
function codeOf(failure: unknown): { code: string; message: string } {
  const envelope = failure as { error?: { code?: string; message?: string } } | undefined;
  return { code: envelope?.error?.code ?? "REQUEST_FAILED", message: envelope?.error?.message ?? "The request could not be completed. Please try again." };
}
