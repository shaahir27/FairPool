import { useEffect, useState } from "react";

import {
  api,
  formatCents,
  formatDateTime,
  HonestyLabels,
  Notice,
  REJECT_REASON_LABELS,
  StatusPill,
  statusStyle,
} from "../shared";

interface Receipt {
  payload: {
    commitment: string;
    entry_id: string;
    pool_id: string;
    received_at: string;
    v: number;
  };
  salt_hex: string;
  request_hash: string;
  signature: string;
}

interface OrderStatus {
  buyer_order_id: string;
  status: string;
  lot_status: string;
  total_cents: number;
  history: { status: string; at: string }[];
  paypal: {
    authorization_status: string | null;
    capture_status: string | null;
    refund_status: string | null;
  };
  labels: string[];
  pool_id: string | null;
  lot_id: string | null;
  placed_at: string | null;
  reject_reason: string | null;
  receipt: Receipt | null;
}

const REASON_STATES = new Set(["REJECTED", "AUTH_FAILED", "CAPTURE_FAILED"]);

export function OrderStatusCard({ buyerOrderId }: { buyerOrderId: string }) {
  const [order, setOrder] = useState<OrderStatus | null>(null);
  const [error, setError] = useState<{ code: string; message: string } | null>(null);
  const [receiptOpen, setReceiptOpen] = useState(false);

  useEffect(() => {
    let live = true;
    void api
      .GET("/api/v1/orders/{buyer_order_id}", {
        params: { path: { buyer_order_id: buyerOrderId } },
      })
      .then(({ data, error: failure }) => {
        if (!live) return;
        if (failure) {
          const envelope = failure as { error?: { code?: string; message?: string } };
          setError({
            code: envelope.error?.code ?? "REQUEST_FAILED",
            message: envelope.error?.message ?? "The order could not be loaded.",
          });
          return;
        }
        setOrder(data as unknown as OrderStatus);
      });
    return () => {
      live = false;
    };
  }, [buyerOrderId]);

  if (error) {
    return (
      <Notice kind="error" code={error.code}>
        {error.message}
      </Notice>
    );
  }
  if (!order) {
    return <div className="h-40 animate-pulse rounded-2xl bg-line/40" aria-label="Loading order" />;
  }

  const orderStyle = statusStyle(order.status);
  const lotStyle = statusStyle(order.lot_status);
  const lastAt = order.history.at(-1)?.at;

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-xs text-muted">Orders / {order.buyer_order_id.slice(0, 13)}…</p>
          <h1 className="font-display text-4xl leading-tight">Order status</h1>
        </div>
        <div className="flex items-center gap-2">
          <HonestyLabels kinds={["sandbox", "fallback"]} />
          {order.receipt ? (
            <button
              type="button"
              className="press rounded-xl bg-accent px-4 py-2 text-sm font-semibold text-ink"
              aria-expanded={receiptOpen}
              onClick={() => setReceiptOpen((open) => !open)}
            >
              View entry receipt
            </button>
          ) : null}
        </div>
      </div>

      <dl className="grid gap-4 rounded-2xl border border-line bg-surface p-5 sm:grid-cols-3">
        <Cell label="Order ID" mono value={order.buyer_order_id} />
        <Cell label="Pool" mono value={order.pool_id ?? "—"} />
        <Cell label="Placed" value={order.placed_at ? formatDateTime(order.placed_at) : "—"} />
      </dl>

      <div className="grid gap-4 md:grid-cols-2">
        <section className={`rounded-2xl p-6 ${orderStyle.tone === "bad" ? "bg-danger-soft" : orderStyle.tone === "good" ? "bg-ink text-canvas" : "bg-accent-soft"}`}>
          <p className="text-xs uppercase tracking-label opacity-70">Order status</p>
          <p className="mt-1 font-mono text-lg">{order.status}</p>
          <p className="mt-2 text-sm opacity-80">{orderStyle.label}{lastAt ? ` · since ${formatDateTime(lastAt)}` : ""}</p>
          {order.status === "AUTHORIZING" ? (
            <p className="mt-2 text-sm">
              PayPal is still confirming your hold. This is not a failure, and nothing has been paid yet.
            </p>
          ) : null}
        </section>
        <section className="rounded-2xl border border-line bg-surface p-6">
          <p className="text-xs uppercase tracking-label text-muted">Lot status</p>
          <p className="mt-1 font-mono text-lg">{order.lot_status}</p>
          <p className="mt-2 text-sm text-muted">{lotStyle.label}</p>
        </section>
      </div>

      {REASON_STATES.has(order.status) && order.reject_reason ? (
        <section className="enter-rise rounded-2xl border border-danger/40 bg-danger-soft p-5">
          <p className="text-xs uppercase tracking-label text-danger">Why</p>
          <p className="mt-1 font-mono text-sm">{order.reject_reason}</p>
          <p className="mt-2 text-sm">
            {REJECT_REASON_LABELS[order.reject_reason] ?? "The payment was refused by a server check."}
          </p>
        </section>
      ) : null}

      <div className="grid gap-4 md:grid-cols-[1fr_1.2fr]">
        <section className="rounded-2xl bg-ink p-6 text-canvas">
          <p className="text-xs uppercase tracking-label text-canvas/70">Total</p>
          <p className="font-display text-4xl leading-none">{formatCents(order.total_cents)}</p>
          <dl className="mt-4 space-y-2 text-sm">
            <ProviderRow label="Authorization" value={order.paypal.authorization_status} />
            <ProviderRow label="Capture" value={order.paypal.capture_status} />
            <ProviderRow label="Refund" value={order.paypal.refund_status} />
          </dl>
        </section>
        <section className="rounded-2xl border border-line bg-surface p-6">
          <p className="text-xs uppercase tracking-label text-muted">Journey</p>
          <ol className="mt-3 space-y-2 text-sm">
            {order.history.map((item) => (
              <li key={`${item.status}-${item.at}`} className="flex items-center justify-between gap-3">
                <StatusPill status={item.status} tone={statusStyle(item.status).tone} />
                <span className="font-mono text-xs text-muted">{formatDateTime(item.at)}</span>
              </li>
            ))}
            {order.history.length === 0 ? <li className="text-muted">No transitions recorded yet.</li> : null}
          </ol>
        </section>
      </div>

      {receiptOpen && order.receipt ? (
        <section className="enter-rise rounded-2xl border border-line bg-surface p-6">
          <h2 className="text-lg font-semibold">Entry receipt</h2>
          <p className="mt-1 text-sm text-muted">
            Proof that your entry was received. Check it on the public audit page.
          </p>
          <dl className="mt-4 grid gap-3 text-sm">
            <Cell label="Commitment" mono value={order.receipt.payload.commitment} />
            <Cell label="Entry ID" mono value={order.receipt.payload.entry_id} />
            <Cell label="Pool ID" mono value={order.receipt.payload.pool_id} />
            <Cell label="Received" value={formatDateTime(order.receipt.payload.received_at)} />
            <Cell label="Salt" mono value={order.receipt.salt_hex} />
            <Cell label="Request hash" mono value={order.receipt.request_hash} />
            <Cell label="Signature" mono value={order.receipt.signature} />
          </dl>
          <a
            className="mt-4 inline-block text-sm font-semibold underline decoration-accent decoration-2 underline-offset-4"
            href={`/audit/${order.pool_id ?? order.receipt.payload.pool_id}`}
          >
            Check it on the public audit page
          </a>
        </section>
      ) : null}
    </div>
  );
}

function Cell({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-label text-muted">{label}</dt>
      <dd className={`mt-1 break-all ${mono ? "font-mono text-xs" : "text-sm"}`}>{value}</dd>
    </div>
  );
}

function ProviderRow({ label, value }: { label: string; value: string | null }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <dt className="text-canvas/70">{label}</dt>
      <dd>
        {value ? <StatusPill status={value} tone="neutral" /> : <span className="text-canvas/50">—</span>}
      </dd>
    </div>
  );
}
