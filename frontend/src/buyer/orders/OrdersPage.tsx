import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import {
  api,
  useApiRead,
  type ApiComponents,
  envelope,
  formatCents,
  formatDateTime,
  honestyKinds,
  HonestyLabels,
  ProductArt,
  Icon,
  Notice,
  StatusPill,
  statusStyle,
} from "../../shared";
import "../settings.css";

type MeOrder = ApiComponents["schemas"]["MeOrder"];
type Outcome = "in-progress" | "paid" | "released" | "not-completed";

const GROUPS: readonly { id: Outcome; title: string; note: string }[] = [
  { id: "in-progress", title: "In progress", note: "Offers and payments that have not reached a final outcome." },
  { id: "paid", title: "Paid", note: "PayPal confirmed a completed capture." },
  { id: "released", title: "Released", note: "Holds released and refunds confirmed." },
  { id: "not-completed", title: "Not completed", note: "Declined, expired or stopped by a check." },
];

const RELEASED = new Set(["VOIDED", "REFUNDED"]);
const NOT_COMPLETED = new Set(["EXPIRED", "DECLINED", "REJECTED", "AUTH_FAILED", "CAPTURE_FAILED"]);

/** Outcome groups follow the shared order vocabulary; unknown states stay visible in progress. */
function outcomeOf(status: string): Outcome {
  if (status === "CAPTURED") return "paid";
  if (RELEASED.has(status)) return "released";
  if (NOT_COMPLETED.has(status)) return "not-completed";
  return "in-progress";
}

export function OrdersPage() {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Outcome | "all">("all");
  const history = useApiRead("/api/v1/me/orders", (signal) => api.GET("/api/v1/me/orders", {signal}));
  const orders: MeOrder[] | null = history.data?.items ?? null;
  const error = history.error ? envelope(history.error) : null;
  const [captures, setCaptures] = useState<Record<string, string | null>>({});
  const [captureProblems, setCaptureProblems] = useState<Record<string, string>>({});
  const [copyMessage, setCopyMessage] = useState("");

  // CR-10 supplies capture references in the list. Older API versions still use
  // the existing detail read; a failed read never means "no capture".
  useEffect(() => {
    if (!orders || orders.length === 0) return;
    let live = true;
    setCaptures({});
    setCaptureProblems({});
    const load = async (buyerOrderId: string) => {
      try {
        const { data, error: failure } = await api.GET("/api/v1/orders/{buyer_order_id}", {
          params: { path: { buyer_order_id: buyerOrderId } },
        });
        if (!live) return;
        if (failure || !data) {
          setCaptureProblems((current) => ({
            ...current,
            [buyerOrderId]: "The PayPal capture reference could not be loaded.",
          }));
          return;
        }
        setCaptures((current) => ({
          ...current,
          [buyerOrderId]: data.paypal?.capture_id ?? null,
        }));
      } catch {
        if (!live) return;
        setCaptureProblems((current) => ({
          ...current,
          [buyerOrderId]: "The PayPal capture reference could not be loaded.",
        }));
      }
    };
    void Promise.all(orders.filter((order) => order.capture_id === undefined).map((order) => load(order.buyer_order_id)));
    return () => {
      live = false;
    };
  }, [orders]);

  async function copyCapture(value: string): Promise<void> {
    try {
      if (!navigator.clipboard?.writeText) throw new Error("clipboard unavailable");
      await navigator.clipboard.writeText(value);
      setCopyMessage("PayPal payment reference copied.");
    } catch {
      setCopyMessage("The reference could not be copied. Select it and copy it manually.");
    }
  }

  const search = query.trim().toLowerCase();
  const visible = (orders ?? []).filter((order) => (filter === "all" || outcomeOf(order.status) === filter) && (!search || [order.product?.title, order.pool_title, order.merchant?.display_name].some((part) => part?.toLowerCase().includes(search))));
  return <section aria-labelledby="orders-title" className="orders-page">
    <header className="settings-heading"><h1 id="orders-title" className="shop-title">Orders</h1><p className="shop-copy">Your purchases, payment updates and order details.</p></header>
    {error ? <Notice kind="warn" code={error.code}>We could not load your orders. {error.message} <button type="button" className="signup-back" onClick={() => void history.refetch()}>Try again</button></Notice> : null}
    {copyMessage ? <p role="status" className="shop-copy">{copyMessage}</p> : null}
    {orders === null ? error ? null : <div role="status" aria-busy="true" aria-label="Loading your orders" className="purchase-feed">{[0,1,2].map((index) => <div key={index} className="shop-panel shop-panel-pad"><div className="skeleton h-5 w-1/2" /><div className="skeleton mt-4 h-4 w-2/3" /></div>)}</div>
      : orders.length === 0 ? <div className="pool-list-empty"><Icon name="bag" /><h2>No orders yet</h2><p>Your order will appear here when a pool sends you an offer.</p><Link className="button-secondary" to="/discover">Find a pool to join<Icon name="arrow" /></Link></div>
      : <><div className="order-list-controls"><label className="catalogue-search"><Icon name="search" /><span className="sr-only">Search your orders</span><input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search product or merchant" /></label>
        <label className="order-status-filter">Payment status<select className="form-input" value={filter} onChange={(event) => setFilter(event.target.value as Outcome | "all")}><option value="all">All orders</option>{GROUPS.map((group) => <option key={group.id} value={group.id}>{group.title}</option>)}</select></label></div>
        <p role="status" className="pool-list-summary">{visible.length} {visible.length === 1 ? "order" : "orders"}{filter !== "all" || search ? " match your filters" : " in your history"}.</p>
        {visible.length === 0 ? <div className="pool-list-empty"><Icon name="search" /><h2>No matching orders</h2><p>Try another product name or payment status.</p><button type="button" className="button-secondary" onClick={() => {setQuery(""); setFilter("all");}}>Clear filters</button></div>
          : <ul className="purchase-feed" aria-label="Your orders">{visible.map((order) => <OrderRow key={order.buyer_order_id} order={order} capture={order.capture_id === undefined ? captures[order.buyer_order_id] : order.capture_id} captureProblem={captureProblems[order.buyer_order_id]} onCopyCapture={(value) => void copyCapture(value)} />)}</ul>}
      </>}
  </section>;
}

function OrderRow({
  order,
  capture,
  captureProblem,
  onCopyCapture,
}: {
  order: MeOrder;
  capture: string | null | undefined;
  captureProblem: string | undefined;
  onCopyCapture: (value: string) => void;
}) {
  const style = statusStyle(order.status);
  const hasReceipt = Boolean(order.receipt);
  return (
    <li className="purchase-record">
      <div className="purchase-heading">
          <div className="order-purchase-product">
            {order.product ? <ProductArt title={order.product.title} /> : null}
            <div><h2>{order.product?.title ?? order.pool_title ?? "Order details"}</h2>
              {order.merchant ? <p className="purchase-merchant">{order.merchant.display_name}</p> : null}
              {order.product ? <p className="entry-product-variant">{[order.product.variant, order.product.condition].filter(Boolean).join(", ")}</p> : null}
              {order.placed_at ? <p className="purchase-date">Ordered {formatDateTime(order.placed_at)}</p> : null}
            </div>
          </div>
        <div className="text-left sm:text-right">
          <p className="text-xl font-semibold tracking-tight tabular-nums">
            {formatCents(order.total_cents)} <span className="text-xs font-normal text-muted">USD</span>
          </p>
          <Link
            className="signup-back mt-1 inline-flex min-h-[44px] items-center gap-2"
            to={`/orders/${order.buyer_order_id}`}
            aria-label={`${hasReceipt ? "Open order and receipt for" : "Open order for"} ${order.buyer_order_id}`}
          >
            View order
            <Icon name="arrow" />
          </Link>
        </div>
      </div>
          <div className="purchase-order-status">
            <StatusPill status={order.status} tone={style.tone}>
              {style.label}
            </StatusPill>

          </div>
          {order.terms ? <p className="purchase-terms">Delivery within {order.terms.delivery_sla_days} days. {order.terms.returns_days}-day returns</p> : null}
          {order.labels && honestyKinds(order.labels).some((kind) => kind !== "sandbox") ? <div className="mt-3"><HonestyLabels kinds={honestyKinds(order.labels).filter((kind) => kind !== "sandbox")} /></div> : null}
          <details className="entry-technical-details"><summary>Order details and references</summary>
          <p className="entry-reference">Order reference: <code>{order.buyer_order_id}</code></p><p className="entry-reference">Order status: <code>{order.status}</code></p>
          <p className="mt-2 flex items-center gap-1.5 text-xs text-muted">
            <Icon name={hasReceipt ? "receipt" : "info"} />
            {hasReceipt ? "Entry receipt available" : "No entry receipt for this order"}
          </p>
          {capture ? (
            <p className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
              <Icon name="wallet" />
              <span className="text-muted">PayPal capture</span>
              <code className="break-all font-mono text-[0.6875rem]">{capture}</code>
              <button
                type="button"
                className="icon-button"
                aria-label={`Copy PayPal capture reference for ${order.buyer_order_id}`}
                onClick={() => onCopyCapture(capture)}
              >
                <Icon name="copy" />
              </button>
            </p>
          ) : captureProblem ? (
            <p className="mt-2 flex items-center gap-1.5 text-xs text-muted">
              <Icon name="info" />
              {captureProblem}
            </p>
          ) : capture === null ? (
            <p className="mt-2 flex items-center gap-1.5 text-xs text-muted">
              <Icon name="info" />
              No PayPal capture yet.
            </p>
          ) : null}
          </details>
    </li>
  );
}
