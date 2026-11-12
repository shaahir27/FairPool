import { type FormEvent, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, type ApiComponents, formatCents, formatDateTime, Icon, Notice, ProductArt, StatusPill, startRouteTransition, useCountdown } from "../shared";

import { PayPalButton } from "./PayPalButton";

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

export function OfferCheckout({
  buyerOrderId,
  onChanged,
}: {
  buyerOrderId: string;
  /** Fired after PayPal confirms an approval, so a list showing this entry can reload. */
  onChanged?: (() => void) | undefined;
}) {
  const [offer, setOffer] = useState<Offer | null>(null);
  const [error, setError] = useState<{ code: string; message: string } | null>(null);
  // Approval reloads the offer instead of guessing the new state in the browser.
  const [reload, setReload] = useState(0);
  const shownFor = useRef<string | null>(null);
  useEffect(() => {
    let live = true;
    if (shownFor.current !== buyerOrderId) setOffer(null);
    setError(null);
    void api.GET("/api/v1/offers/{buyer_order_id}", { params: { path: { buyer_order_id: buyerOrderId } } })
      .then(({ data, error: failure }) => {
        if (!live) return;
        if (failure || !data) setError(codeOf(failure));
        else {
          setOffer(data);
          shownFor.current = buyerOrderId;
        }
      }).catch(() => { if (live) setError({ code: "REQUEST_FAILED", message: "Check your connection and reload this offer." }); });
    return () => { live = false; };
  }, [buyerOrderId, reload]);
  const failure = error ? <Notice kind="error" code={error.code}>{error.message}{" "}<button type="button" className="signup-back" onClick={() => setReload((count) => count + 1)}>Retry offer</button></Notice> : null;
  if (!offer || shownFor.current !== buyerOrderId) return <section className="shop-panel shop-panel-pad" role={error ? undefined : "status"} aria-label={error ? undefined : "Loading offer"} aria-busy={error ? undefined : true}><h1 className="shop-title">Review your offer</h1>{failure ?? <><p className="shop-copy mt-2">Loading the merchant and your exact total...</p><div className="skeleton mt-5 h-10 w-2/3" /><div className="skeleton mt-4 h-40" /></>}</section>;
  return <>{failure}<OfferDetails key={buyerOrderId} offer={offer} onRefresh={() => setReload((count) => count + 1)} onChanged={onChanged} /></>;
}

function OfferDetails({ offer, onRefresh, onChanged }: { offer: Offer; onRefresh: () => void; onChanged?: (() => void) | undefined }) {
  const navigate = useNavigate();
  const [address, setAddress] = useState(EMPTY_ADDRESS);
  const [savedAddresses, setSavedAddresses] = useState<ApiComponents["schemas"]["SavedAddressResponse"][]>([]);
  const [selectedAddress, setSelectedAddress] = useState("");
  const [addressLoadFailed, setAddressLoadFailed] = useState(false);
  const addressEdited = useRef(false);
  useEffect(() => {
    let live = true;
    void api.GET("/api/v1/me/addresses").then(({ data, error: failure }) => {
      if (!live) return;
      if (failure || !data || !Array.isArray(data.addresses)) { setAddressLoadFailed(true); return; }
      setSavedAddresses(data.addresses);
      const preferred = data.addresses.find((item) => item.is_default);
      if (preferred && !addressEdited.current) {
        setAddress({ ...EMPTY_ADDRESS, ...preferred.address }); setSelectedAddress(preferred.id);
      }
    }).catch(() => { if (live) setAddressLoadFailed(true); });
    return () => { live = false; };
  }, []);
  // Public SDK values only; a failed load keeps the verified redirect path.
  const [checkoutConfig, setCheckoutConfig] = useState<ApiComponents["schemas"]["CheckoutConfigResponse"] | null>(null);
  const [sdkFallback, setSdkFallback] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    void api.GET("/api/v1/checkout/config").then(({ data }) => {
      if (live && data) setCheckoutConfig(data);
    }).catch(() => {});
    return () => { live = false; };
  }, []);
  const sdkPopup = checkoutConfig?.approval_ui === "sdk_popup" && sdkFallback === null;
  const [busy, setBusy] = useState<"continue" | "decline" | null>(null);
  const [error, setError] = useState<{ code: string; message: string } | null>(null);
  const countdown = useCountdown(offer.offer_expires_at, offer.server_now, offer.offer_started_at);
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
  const ensureShipping = () => {
    // The browser's `required` only helps when the inputs are inside the form;
    // both payment paths check here so an incomplete address never reaches the API.
    const missingFields = ADDRESS_FIELDS.filter(
      (field) => field.required && !address[field.name].trim(),
    ).map((field) => field.label);
    if (missingFields.length === 0) return true;
    setError({ code: "VALIDATION_ERROR", message: `Add ${missingFields.join(", ")}.` });
    return false;
  };
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (busy || countdown.expired) return;
    setBusy("continue"); setError(null);
    if (!ensureShipping()) { setBusy(null); return; }
    try {
      const { data, error: failure } = await api.POST("/api/v1/offers/{buyer_order_id}/continue", {
        params: { path: { buyer_order_id: offer.buyer_order_id } }, body: { shipping: address },
      });
      if (failure || !data) {
        const detail = codeOf(failure);
        setError(detail);
        if (detail.code === "OFFER_EXPIRED" || detail.code === "ORDER_STATE_INVALID") onRefresh();
        return;
      }
      // I14, INT-7: never log the approval URL; no amount leaves the browser.
      window.location.assign(data.approve_url);
    } catch { setError({ code: "REQUEST_FAILED", message: "Check your connection and try again." }); }
    finally { setBusy(null); }
  };
  const terminal = offer.status !== "OFFERED" && offer.status !== "ORDER_CREATED";
  if (terminal || countdown.expired) {
    const expired = offer.status === "EXPIRED" || (!terminal && countdown.expired);
    return <section className="shop-panel shop-panel-pad terminal-offer">
      <Link className="shop-back" to={offer.pool_id ? `/pools/${offer.pool_id}` : "/my-pools"}><Icon name="arrow" />Back to your pool</Link>
      <Icon name={expired ? "clock" : "receipt"} />
      <StatusPill status={expired ? "EXPIRED" : offer.status} />
      <h1>{expired ? "This offer can no longer be approved." : offer.status === "DECLINED" ? "Offer declined" : "Your offer has moved on"}</h1>
      <p className="shop-copy mt-3">{offer.product.title} from {offer.merchant.display_name}</p>
      <p className="secondary-copy mt-3">{expired ? "Your approval window has ended. Check your order for the latest status." : "Check your order for the latest payment and lot status."}</p>
      <Link to={orderPath} className="button-secondary mt-6">View order status <Icon name="arrow" /></Link>
    </section>;
  }
  return <div className="shop-checkout">
    <Link className="shop-back" to={offer.pool_id ? `/pools/${offer.pool_id}` : "/my-pools"}><Icon name="arrow" />Back to your pool</Link>
    <div className="shop-heading">
      <h1 className="shop-title">Review your offer</h1>
      <p className="shop-copy">Check the merchant, exact total and terms, then choose your delivery address.</p>
    </div>
    {offer.notices.fallback ? <p className="preview-disclosure"><Icon name="info" /><span><strong>Sandbox fallback. </strong>{offer.notices.fallback}</span></p> : null}
    {error ? <div className="mb-4"><Notice kind="error" code={error.code}>{error.message}</Notice></div> : null}
    <section className="shop-panel shop-panel-pad offer-overview" aria-label="Order summary">
      <div className="offer-review-grid">
        <div>
          <div className="shop-product-row"><ProductArt title={offer.product.title} small /><div><h2>{offer.product.title}</h2><p>{[offer.product.variant, offer.product.condition].filter(Boolean).join(" - ")}</p><p>Sold by {offer.merchant.display_name} - 1 item</p><p className="offer-art-note">Category illustration; see the merchant's exact terms below.</p></div></div>

        </div>
        <div className="offer-price-summary">
          <p className="offer-total-label">Delivered total <span>USD</span></p>
          <p className="offer-total-amount">{formatCents(offer.totals.total_cents)}</p>
          <p className="shop-copy">Your confirmed maximum: <strong>{formatCents(offer.totals.cap_cents)}</strong></p>
          <dl className="price-rows"><Price label="Item" cents={offer.totals.item_cents} /><Price label="Shipping" cents={offer.totals.shipping_cents} /><Price label="Tax" cents={offer.totals.tax_cents} /></dl>
        </div>
          <dl className="offer-awarded-terms"><div><dt>Delivery</dt><dd>Within {offer.terms.delivery_sla_days} days</dd></div><div><dt>Returns</dt><dd>{offer.terms.returns_days}-day return terms</dd></div><div className="offer-included"><dt>Included items</dt><dd>{offer.product.bundle_contents.join(", ")}</dd></div></dl>
      </div>
    </section>
    <form id="checkout-form" className="shop-checkout-grid" onSubmit={(event) => void submit(event)}>
      <div className="shop-checkout-main">
        <section className="shop-panel shop-panel-pad" aria-labelledby="delivery-heading">
          <div className="shop-section-heading"><Icon name="truck" /><h2 id="delivery-heading">Delivery details</h2></div>
          <p className="shop-copy">Where should your order be sent?</p>
          {savedAddresses.length > 0 ? <label className="saved-address-select">Delivery address<select className="form-input" value={selectedAddress} onChange={(event) => {
            addressEdited.current = true; setSelectedAddress(event.target.value);
            const saved = savedAddresses.find((item) => item.id === event.target.value);
            setAddress(saved ? { ...EMPTY_ADDRESS, ...saved.address } : EMPTY_ADDRESS);
          }}><option value="">Use a different address</option>{savedAddresses.map((item) => <option key={item.id} value={item.id}>{item.address.name} — {item.address.line1}{item.is_default ? " (default)" : ""}</option>)}</select></label> : null}
          {addressLoadFailed ? <p className="signup-help">Saved addresses couldn’t be loaded. You can enter your delivery details below.</p> : null}
          <div className="shop-address-fields">
            {ADDRESS_FIELDS.map((field) => field.name === "line2" ? <details key={field.name} className="optional-address"><summary><span aria-hidden="true">+</span> Add apartment, suite or floor</summary><label>Address line 2 (optional)<input name="line2" autoComplete="address-line2" className="form-input" value={address.line2} maxLength={200} onChange={(event) => { addressEdited.current = true; setSelectedAddress(""); setAddress((previous) => ({ ...previous, line2: event.target.value })); }} /></label></details> : <label key={field.name} className={["name", "line1"].includes(field.name) ? "address-full" : field.name === "country_code" ? "country-field" : ""}>
              {field.label}<input name={field.name} autoComplete={field.autoComplete} className="form-input" value={address[field.name]} required={field.required}
                maxLength={field.name === "country_code" ? 2 : field.name === "postal_code" ? 20 : 200}
                pattern={field.name === "country_code" ? "[A-Za-z]{2}" : undefined}
                onChange={(event) => { addressEdited.current = true; setSelectedAddress(""); setAddress((previous) => ({ ...previous, [field.name]: event.target.value })); }} />
            </label>)}
          </div>
          <Link className="signup-back" to="/settings/addresses">Manage saved addresses</Link>
        </section>

      </div>
        <section className="shop-panel shop-panel-pad offer-payment" aria-labelledby="payment-heading">
          <div className="shop-section-heading"><Icon name="wallet" /><h2 id="payment-heading">Approve this offer</h2></div>
          <div className={`reservation-note ${countdown.urgent ? "is-urgent" : ""}`}><span><Icon name="clock" />{offer.server_now ? "Offer expires in" : "Review deadline"}</span><time dateTime={offer.offer_expires_at}>{offer.server_now ? countdown.label : formatDateTime(offer.offer_expires_at)}</time></div>
          {offer.server_now ? <p className="signup-help">Review by {formatDateTime(offer.offer_expires_at)}.</p> : null}
          <div className="payment-choice"><span className="paypal-word">PayPal</span><p className="shop-copy">Continue on PayPal to review your payment.</p><Icon name="lock" /></div>
          <p className="payment-description">{offer.notices.hold}</p>
          {sdkFallback ? <div className="mb-4"><Notice kind="info">{sdkFallback}</Notice></div> : null}
          <div className="checkout-actions">
            {sdkPopup && checkoutConfig ? (
              <PayPalButton
                config={checkoutConfig}
                buyerOrderId={offer.buyer_order_id}
                shipping={address}
                disabled={busy !== null || countdown.expired}
                ensureShipping={ensureShipping}
                onRefresh={onRefresh}
                onApproved={onChanged}
                onFallback={setSdkFallback}
              />
            ) : (
              <button type="submit" disabled={busy !== null || countdown.expired} className="button-primary w-full">{busy === "continue" ? "Opening PayPal…" : <>Continue to PayPal <Icon name="arrow" /></>}</button>
            )}
          </div>
          <details className="shop-disclosure offer-rules"><summary>How this offer was chosen<Icon name="down" /></summary><p>Qualifying merchant bids are ranked under this pool's published rules. The exact total is checked against your confirmed maximum.</p><p>{offer.notices.lots_may_differ}</p>{offer.pool_id ? <Link to={`/audit/${offer.pool_id}`}>View this pool's published rules</Link> : null}</details>
          <p className="checkout-fineprint"><Icon name="lock" />Your address is stored encrypted.</p>
          <button type="button" disabled={busy !== null} onClick={() => void decline()} className="decline-link">{busy === "decline" ? "Declining…" : "Decline this offer"}</button>
        </section>
    </form>
  </div>;
}

function Price({ label, cents }: { label: string; cents: number }) { return <div><dt>{label}</dt><dd>{formatCents(cents)}</dd></div>; }
function codeOf(failure: unknown): { code: string; message: string } {
  const envelope = failure as { error?: { code?: string; message?: string } } | undefined;
  return { code: envelope?.error?.code ?? "REQUEST_FAILED", message: envelope?.error?.message ?? "The request could not be completed. Please try again." };
}
