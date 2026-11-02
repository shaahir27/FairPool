import { type ReactNode, useEffect, useId, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { Link } from "react-router-dom";
import { api, type ApiComponents, formatCents, formatDateTime, Icon, Notice, REJECT_REASON_LABELS, StatusPill, statusStyle } from "../shared";
import { ProductArt } from "./OfferCheckout";
import { ReceiptDrawer } from "./ReceiptDrawer";

type OrderStatus = ApiComponents["schemas"]["OrderStatusResponse"];
const ORDER_COPY: Record<string, string> = {
  AUTHORIZING: "PayPal is still confirming your hold. This is not a failure, and nothing has been paid yet.",
  AUTHORIZED: "Your hold is confirmed. A hold is not a completed payment.",
  CAPTURE_PENDING: "PayPal is still confirming your payment. A pending capture does not count as paid.",
  CAPTURED: "PayPal confirmed your payment. Check the group status for your lot's outcome.",
  VOIDED: "Your hold was released. No payment was taken on this authorization.",
  REFUNDED: "PayPal confirmed your refund. Your bank may take a few days to show it.",
  REFUNDING: "Your refund is being processed. Check back for PayPal's confirmation.",
  DECLINED: "You declined this offer. Check My Pools for your other entries.",
  EXPIRED: "The approval window for this offer has ended.",
};
const ORDER_TITLES: Record<string, string> = {
  OFFERED: "Your offer is ready", ORDER_CREATED: "Ready for your approval",
  APPROVED: "Approval received", AUTHORIZING: "Confirming your hold",
  AUTHORIZED: "Your hold is confirmed", CAPTURING: "Completing your payment",
  CAPTURE_PENDING: "Waiting for PayPal", CAPTURED: "Your payment is complete",
  VOIDED: "Your hold has been released", REFUNDED: "Your refund is confirmed",
  REFUNDING: "Your refund is on its way", DECLINED: "Offer declined",
  EXPIRED: "This offer has expired", REJECTED: "This payment needs attention",
  AUTH_FAILED: "The hold could not be placed", CAPTURE_FAILED: "The payment did not complete",
};
const CLOSED_ORDERS = new Set(["VOIDED", "REFUNDED", "DECLINED", "EXPIRED", "REJECTED", "AUTH_FAILED", "CAPTURE_FAILED"]);

export function OrderStatusCard({ buyerOrderId }: { buyerOrderId: string }) {
  const [order, setOrder] = useState<OrderStatus | null>(null);
  const [error, setError] = useState<{ code: string; message: string } | null>(null);
  const [receiptOpen, setReceiptOpen] = useState(false);
  const [revision, setRevision] = useState(0);
  const [refreshing, setRefreshing] = useState(false);
  const [offer, setOffer] = useState<ApiComponents["schemas"]["OfferResponse"] | null>(null);
  const [buyerName, setBuyerName] = useState<string | null>(null);
  const reduced = useReducedMotion();

  useEffect(() => {
    let live = true;
    setOffer(null); setBuyerName(null); setReceiptOpen(false);
    // Metadata is optional; a failed disclosure lookup must not hide payment status.
    void api.GET("/api/v1/offers/{buyer_order_id}", { params: { path: { buyer_order_id: buyerOrderId } } })
      .then(({ data }) => { if (live && data?.product) setOffer(data); }).catch(() => {});
    void api.GET("/api/v1/me").then(({ data }) => { if (live && data?.display_name) setBuyerName(data.display_name); }).catch(() => {});
    return () => { live = false; };
  }, [buyerOrderId]);

  useEffect(() => {
    let live = true;
    setOrder((current) => current?.buyer_order_id === buyerOrderId ? current : null);
    setError(null); setRefreshing(true);
    void api.GET("/api/v1/orders/{buyer_order_id}", { params: { path: { buyer_order_id: buyerOrderId } } })
      .then(({ data, error: failure }) => {
        if (!live) return;
        if (failure || !data) {
          const value = failure as { error?: { code?: string; message?: string } } | undefined;
          setError({ code: value?.error?.code ?? "REQUEST_FAILED", message: value?.error?.message ?? "The order could not be loaded." });
        } else setOrder(data);
      }).catch(() => { if (live) setError({ code: "REQUEST_FAILED", message: "Check your connection and try again." }); })
      .finally(() => { if (live) setRefreshing(false); });
    return () => { live = false; };
  }, [buyerOrderId, revision]);

  if (!order && error) return <><Notice kind="error" code={error.code}>{error.message}</Notice><button type="button" className="shop-quiet-button mt-4" onClick={() => setRevision((n) => n + 1)}>Try again</button></>;
  if (!order) return <section className="shop-panel shop-panel-pad" aria-busy="true" role="status" aria-label="Loading order"><h1 className="shop-title">Order status</h1><div className="skeleton mt-5 h-40" /></section>;

  const history = order.history ?? [];
  const negative = CLOSED_ORDERS.has(order.status);
  const copy = ORDER_COPY[order.status] ?? statusStyle(order.status).label;
  const funded = order.lot_status === "FUNDED" || order.lot_status === "CLOSED";
  const failedLot = ["FAILING", "FAILED_CLOSED", "CANCELLED"].includes(order.lot_status);
  const milestones = [
    { title: "Your offer", text: "Individual order", done: history.some((item) => item.status === "OFFERED"), current: order.status === "OFFERED" },
    { title: "Payment", text: order.status === "CAPTURED" ? "Completed" : negative ? "See outcome" : "In progress", done: order.status === "CAPTURED", current: !negative && !funded && order.status !== "OFFERED" },
    { title: "Group funding", text: funded ? "Minimum reached" : failedLot ? "See group status" : "Waiting for minimum", done: funded, current: funded },
    { title: "Delivery", text: "After funding", done: false, current: false },
  ];

  return <div className="order-view">
    <div className="order-page-heading">
      <div><Link className="shop-back" to="/orders"><Icon name="arrow" />All orders</Link><h1 className="shop-title">Order status</h1><p className="shop-copy">Follow your payment and your group's progress in one place.</p></div>
      <div className="order-page-actions"><button type="button" className="shop-quiet-button" disabled={refreshing} onClick={() => setRevision((n) => n + 1)}><Icon name="returns" />{refreshing ? "Refreshing..." : "Refresh status"}</button>{order.receipt ? <button type="button" className="shop-quiet-button" aria-haspopup="dialog" aria-expanded={receiptOpen} onClick={() => setReceiptOpen(true)}><Icon name="receipt" />View entry receipt</button> : null}</div>
    </div>
    {error ? <div className="mb-5"><Notice kind="error" code={error.code}>{error.message} Your last loaded status is still shown.</Notice></div> : null}
    {order.reject_reason ? <div className="mb-5"><Notice kind="error" code={order.reject_reason}>{REJECT_REASON_LABELS[order.reject_reason] ?? "The payment was refused by a server check."}</Notice></div> : null}
    <div className="order-display-grid">
      <div className="order-primary-column">
        <section className="shop-panel" aria-label="Order progress">
          <AnimatePresence mode="wait" initial={false}>
            <motion.div key={order.status} className={`order-current ${negative ? "is-negative" : ""}`} initial={{ opacity: 0, transform: reduced ? "none" : "translateY(6px)" }} animate={{ opacity: 1, transform: "none" }} exit={{ opacity: 0 }} transition={{ duration: reduced ? 0 : .2, ease: [.23, 1, .32, 1] }}>
              <span className="order-current-symbol"><Icon name={negative ? "returns" : order.status === "CAPTURED" ? "check" : "clock"} /></span>
              <div><h2>{ORDER_TITLES[order.status] ?? statusStyle(order.status).label}</h2><p className="shop-copy">{copy}</p><code className="order-code">{order.status}</code></div>
            </motion.div>
          </AnimatePresence>
          <ol className="order-milestones" aria-label="Your order journey">{milestones.map((stage, index) => <li key={stage.title} className={stage.done ? "milestone-recorded" : ""} aria-current={stage.current ? "step" : undefined}><span className="milestone-dot">{stage.done ? <Icon name="check" /> : index + 1}</span><strong>{stage.title}</strong><small>{stage.text}</small></li>)}</ol>
          <div className="order-group-note"><Icon name="layers" /><div><strong>{funded ? "Your group reached its minimum" : failedLot ? "This lot is closing or has closed" : "Your purchase is part of a group"}</strong><p>{funded ? "Enough buyers' completed payments met the lot minimum." : failedLot ? statusStyle(order.lot_status).label : "The lot is funded only after enough payments complete. A hold or approval does not count as paid."}</p><code>{order.lot_status}</code></div></div>
        </section>
        {offer ? <section className="shop-panel order-item"><h2>Your item</h2><div className="shop-product-row"><ProductArt title={offer.product.title} small /><div><h3>{offer.product.title}</h3><p>{[offer.product.variant, offer.product.condition].filter(Boolean).join(" · ")}</p><p>Sold by {offer.merchant.display_name}</p><p>Quantity: 1</p></div><strong className="order-item-price">{formatCents(offer.totals.item_cents)}</strong></div><div className="order-item-terms"><span><Icon name="truck" />Delivery within {offer.terms.delivery_sla_days} days</span><span><Icon name="returns" />{offer.terms.returns_days}-day return terms</span><span><Icon name="box" />{offer.product.bundle_contents.join(", ")}</span></div></section> : null}
        <Disclosure title="Payment details" icon="wallet"><p className="shop-copy">States reported by PayPal. Only a completed capture confirms payment.</p><dl className="order-provider-rows"><Provider label="Authorization" value={order.paypal.authorization_status} /><Provider label="Capture" value={order.paypal.capture_status} /><Provider label="Refund" value={order.paypal.refund_status} /></dl>{order.status === "AUTHORIZED" ? <div className="order-withdraw"><button type="button" disabled className="shop-quiet-button" aria-disabled="true">Withdraw before payment</button><p>Holds are released automatically when the lot fails to fund or the offer expires. Requesting a release yourself is a later task: the withdraw route is not in this build.</p></div> : null}</Disclosure>
        <Disclosure title="Order activity" icon="clock">{history.length ? <ol className="order-activity">{history.map((item) => <li key={`${item.status}-${item.at}`}><span className="activity-dot" /><div><strong>{statusStyle(item.status).label}</strong><code>{item.status}</code></div><time dateTime={item.at}>{formatDateTime(item.at)}</time></li>)}</ol> : <p className="shop-copy">No events have been recorded yet.</p>}</Disclosure>
      </div>
      <aside className="order-secondary-column" aria-label="Order information">
        <section className="shop-panel order-info"><h2>Order information</h2><dl><Info label="Order number" value={order.buyer_order_id} mono />{buyerName ? <Info label="Ordered by" value={buyerName} /> : null}<Info label="Placed" value={order.placed_at ? formatDateTime(order.placed_at) : "Not reported"} />{offer ? <Info label="Merchant" value={offer.merchant.display_name} /> : null}<Info label="Pool" value={order.pool_id ?? "Not reported"} mono /></dl><div className="order-info-total"><span>Order total <small>USD</small></span><strong>{formatCents(order.total_cents)}</strong></div></section>
        <section className="order-help"><h2>{negative ? "About your outcome" : "What happens next?"}</h2><p>{negative ? copy : funded ? "Your lot is funded. Delivery follows the merchant's stated terms." : "Once the lot's minimum is met by completed payments, it can be funded and the merchant can fulfil the orders."}</p>{offer?.pool_id ? <Link to={`/audit/${offer.pool_id}`}>View pool rules <Icon name="arrow" /></Link> : null}</section>
      </aside>
    </div>
    <div className="order-disclosures">{(order.labels ?? []).map((label) => <span key={label}><Icon name="info" />{label}</span>)}</div>
    {order.receipt ? <ReceiptDrawer receipt={order.receipt} open={receiptOpen} onClose={() => setReceiptOpen(false)} /> : null}
  </div>;
}

function Disclosure({ title, icon, children }: { title: string; icon: "wallet" | "clock"; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const reduced = useReducedMotion();
  return <section className="shop-panel order-expand"><button type="button" className="order-expand-toggle" aria-expanded={open} aria-controls={id} onClick={() => setOpen((value) => !value)}><span><Icon name={icon} />{title}</span><Icon name="down" /></button><AnimatePresence initial={false}>{open ? <motion.div id={id} key="content" className="order-expand-content" initial={{ opacity: 0, transform: reduced ? "none" : "translateY(-4px)" }} animate={{ opacity: 1, transform: "none" }} exit={{ opacity: 0 }} transition={{ duration: reduced ? 0 : .16, ease: [.23, 1, .32, 1] }}>{children}</motion.div> : null}</AnimatePresence></section>;
}
function Info({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) { return <div><dt>{label}</dt><dd className={mono ? "font-mono text-xs" : ""}>{value}</dd></div>; }
function Provider({ label, value }: { label: string; value: string | null | undefined }) { return <div><dt>{label}</dt><dd>{value ? <StatusPill status={value} tone="neutral" /> : <span>Not reported</span>}</dd></div>; }
