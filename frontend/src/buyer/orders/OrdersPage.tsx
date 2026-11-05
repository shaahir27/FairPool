import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import {
  api,
  type ApiComponents,
  envelope,
  formatCents,
  Icon,
  Notice,
  StatusPill,
  statusStyle,
} from "../../shared";
import { loadOrders } from "../prefetch";

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
  const [orders, setOrders] = useState<MeOrder[] | null>(null);
  const [error, setError] = useState<{ code: string; message: string } | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [captures, setCaptures] = useState<Record<string, string | null>>({});
  const [captureProblems, setCaptureProblems] = useState<Record<string, string>>({});
  const [copyMessage, setCopyMessage] = useState("");

  useEffect(() => {
    let live = true;
    setError(null);
    void loadOrders(attempt > 0)
      .then(({ data, error: failure }) => {
        if (!live) return;
        if (failure || !data) setError(envelope(failure));
        else setOrders(Array.isArray(data.items) ? data.items : []);
      })
      .catch(() => {
        if (live) setError({ code: "REQUEST_FAILED", message: "Check your connection and try again." });
      });
    return () => {
      live = false;
    };
  }, [attempt]);

  // The list carries no provider reference, so each order's own read supplies the
  // capture id. A failed read is reported as a failed read, never as "no capture".
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
    void Promise.all(orders.map((order) => load(order.buyer_order_id)));
    return () => {
      live = false;
    };
  }, [orders]);

  async function copyCapture(buyerOrderId: string, value: string): Promise<void> {
    try {
      if (!navigator.clipboard?.writeText) throw new Error("clipboard unavailable");
      await navigator.clipboard.writeText(value);
      setCopyMessage(`PayPal capture reference copied for ${buyerOrderId}.`);
    } catch {
      setCopyMessage("The reference could not be copied. Select it and copy it manually.");
    }
  }

  return (
    <section aria-labelledby="orders-title" className="mx-auto w-full max-w-[1100px]">
      <div className="shop-heading">
        <h1 id="orders-title" className="shop-title">
          Orders
        </h1>
        <p className="shop-copy mt-1" role="status" aria-live="polite" aria-atomic="true">
          {orders === null
            ? error
              ? "Your orders could not be loaded."
              : "Loading your orders."
            : `${orders.length} ${orders.length === 1 ? "order" : "orders"} recorded for you.`}
        </p>
        {copyMessage ? (
          <p className="secondary-copy mt-1" role="status" aria-live="polite">
            {copyMessage}
          </p>
        ) : null}
      </div>

      {error ? (
        <div className="mb-6">
          {/* Polite: the shell may already be announcing its own sign-out alert. */}
          <Notice kind="warn" code={error.code}>
            We couldn’t load your orders. {error.message}{" "}
            <button
              type="button"
              className="signup-back inline-flex min-h-[44px] items-center"
              onClick={() => setAttempt((value) => value + 1)}
            >
              Try again
            </button>
          </Notice>
        </div>
      ) : null}

      {orders === null ? (
        error ? null : (
          <div role="status" aria-busy="true" aria-label="Loading your orders" className="grid gap-4">
            {[0, 1, 2].map((index) => (
              <div key={index} className="panel">
                <div className="skeleton h-5 w-1/3" />
                <div className="skeleton mt-3 h-4 w-2/3" />
              </div>
            ))}
          </div>
        )
      ) : orders.length === 0 ? (
        <section className="panel" aria-labelledby="orders-empty">
          <h2 id="orders-empty">No orders yet</h2>
          <p className="shop-copy mt-2">Orders appear here after you approve an offer and PayPal confirms the payment.</p>
          <Link className="button-secondary mt-5" to="/discover">
            Find a pool to join
            <Icon name="arrow" />
          </Link>
        </section>
      ) : (
        <div className="grid gap-8">
          {GROUPS.map((group) => {
            const grouped = orders.filter((order) => outcomeOf(order.status) === group.id);
            if (grouped.length === 0) return null;
            return (
              <section key={group.id} aria-labelledby={`orders-${group.id}`} className="enter-rise">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <h2 id={`orders-${group.id}`} className="text-lg font-semibold tracking-[-.02em]">
                    {group.title}
                  </h2>
                  <span className="text-xs text-muted">
                    {grouped.length} {grouped.length === 1 ? "order" : "orders"}
                  </span>
                </div>
                <p className="shop-copy mt-1">{group.note}</p>
                <ul className="panel mt-3 divide-y divide-line/60">
                  {grouped.map((order) => (
                    <OrderRow
                      key={order.buyer_order_id}
                      order={order}
                      capture={captures[order.buyer_order_id]}
                      captureProblem={captureProblems[order.buyer_order_id]}
                      onCopyCapture={(value) =>
                        void copyCapture(order.buyer_order_id, value)
                      }
                    />
                  ))}
                </ul>
              </section>
            );
          })}
        </div>
      )}
    </section>
  );
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
    <li className="py-5 first:pt-0 last:pb-0">
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
        <div className="min-w-0">
          <p className="break-all font-mono text-xs text-muted">{order.buyer_order_id}</p>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <StatusPill status={order.status} tone={style.tone}>
              {style.label}
            </StatusPill>
            <code className="text-xs text-muted">{order.status}</code>
          </div>
          <p className="mt-2 flex items-center gap-1.5 text-xs text-muted">
            <Icon name={hasReceipt ? "receipt" : "info"} />
            {hasReceipt ? "Receipt available" : "No receipt for this order"}
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
        </div>
        <div className="text-left sm:text-right">
          <p className="text-xl font-semibold tracking-tight tabular-nums">
            {formatCents(order.total_cents)} <span className="text-xs font-normal text-muted">USD</span>
          </p>
          <Link
            className="signup-back mt-1 inline-flex min-h-[44px] items-center gap-2"
            to={`/orders/${order.buyer_order_id}`}
          >
            {hasReceipt ? "Open order and receipt for" : "Open order for"} {order.buyer_order_id}
            <Icon name="arrow" />
          </Link>
        </div>
      </div>
    </li>
  );
}
