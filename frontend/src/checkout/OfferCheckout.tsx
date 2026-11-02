import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  api,
  AuthLayout,
  formatCents,
  HonestyLabels,
  Notice,
  StatusPill,
  startRouteTransition,
  useCountdown,
} from "../shared";

interface Offer {
  buyer_order_id: string;
  status: string;
  merchant: { display_name: string };
  product: {
    title: string;
    variant: string | null;
    condition: string;
    bundle_contents: string[];
  };
  terms: { delivery_sla_days: number; returns_days: number };
  totals: {
    item_cents: number;
    shipping_cents: number;
    tax_cents: number;
    total_cents: number;
    cap_cents: number;
  };
  offer_expires_at: string;
  offer_started_at: string | null;
  server_now: string | null;
  pool_id: string | null;
  pool_title: string | null;
  notices: { hold: string; lots_may_differ: string; fallback: string | null };
}

const ADDRESS_FIELDS = [
  { name: "name", label: "Name", required: true },
  { name: "line1", label: "Address line 1", required: true },
  { name: "line2", label: "Address line 2 (optional)", required: false },
  { name: "city", label: "City", required: true },
  { name: "region", label: "Region", required: true },
  { name: "postal_code", label: "Postal code", required: true },
  { name: "country_code", label: "Country code", required: true },
] as const;

type AddressField = (typeof ADDRESS_FIELDS)[number]["name"];

export function OfferCheckout({ buyerOrderId }: { buyerOrderId: string }) {
  const navigate = useNavigate();
  const [offer, setOffer] = useState<Offer | null>(null);
  const [error, setError] = useState<{ code: string; message: string } | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [address, setAddress] = useState<Record<AddressField, string>>({
    name: "",
    line1: "",
    line2: "",
    city: "",
    region: "",
    postal_code: "",
    country_code: "",
  });

  useEffect(() => {
    let live = true;
    void api
      .GET("/api/v1/offers/{buyer_order_id}", {
        params: { path: { buyer_order_id: buyerOrderId } },
      })
      .then(({ data, error: failure }) => {
        if (!live) return;
        if (failure) {
          setError(codeOf(failure));
          return;
        }
        setOffer(data as unknown as Offer);
      });
    return () => {
      live = false;
    };
  }, [buyerOrderId]);

  if (error && !offer) {
    return (
      <AuthLayout>
        <div className="mx-auto max-w-xl py-10">
          <Notice kind="error" code={error.code}>
            {error.message}
          </Notice>
        </div>
      </AuthLayout>
    );
  }

  if (!offer) {
    return (
      <AuthLayout>
        <div className="mx-auto max-w-5xl animate-pulse space-y-4 py-10" aria-label="Loading offer">
          <div className="h-10 w-2/3 rounded bg-line/40" />
          <div className="h-24 rounded-xl bg-line/40" />
          <div className="h-40 rounded-xl bg-line/40" />
        </div>
      </AuthLayout>
    );
  }

  const expired = new Date(offer.offer_expires_at).getTime() <= Date.now();
  const decline = async () => {
    await api.POST("/api/v1/offers/{buyer_order_id}/decline", {
      params: { path: { buyer_order_id: buyerOrderId } },
    });
    startRouteTransition(
      () => navigate(`/orders/${buyerOrderId}`),
      `/offers/${buyerOrderId}`,
      `/orders/${buyerOrderId}`,
    );
  };
  const submit = async () => {
    setSubmitting(true);
    setError(null);
    const { data, error: failure } = await api.POST("/api/v1/offers/{buyer_order_id}/continue", {
      params: { path: { buyer_order_id: buyerOrderId } },
      body: { shipping: address },
    });
    if (failure || !data) {
      setSubmitting(false);
      setError(codeOf(failure));
      return;
    }
    // The browser only follows the server's approval URL; it never sends an amount.
    window.location.assign((data as { approve_url: string }).approve_url);
  };

  return (
    <AuthLayout>
      <div className="mx-auto max-w-6xl py-8">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <HonestyLabels kinds={["sandbox", "fallback"]} />
          <StatusPill status={offer.status} />
        </div>
        {offer.notices.fallback ? (
          <div className="mb-4 rounded-xl bg-ink px-5 py-3 text-sm text-canvas">
            {offer.notices.fallback}
          </div>
        ) : null}
        {error ? (
          <div className="mb-4">
            <Notice kind="error" code={error.code}>
              {error.message}
            </Notice>
          </div>
        ) : null}

        <div className="grid gap-5 lg:grid-cols-[1.6fr_1fr]">
          <div className="flex flex-col gap-5">
            <section className="rounded-2xl bg-ink p-7 text-canvas">
              <p className="text-xs uppercase tracking-label text-canvas/70">
                Won by {offer.merchant.display_name}
              </p>
              <h1 className="mt-2 font-display text-4xl leading-tight">{offer.product.title}</h1>
              <div className="mt-3 flex flex-wrap gap-2 text-xs">
                {[offer.product.variant, offer.product.condition]
                  .filter(Boolean)
                  .map((value) => (
                    <span key={String(value)} className="rounded-full border border-canvas/30 px-3 py-1">
                      {value}
                    </span>
                  ))}
                {offer.product.bundle_contents.map((item) => (
                  <span key={item} className="rounded-full bg-canvas/10 px-3 py-1">
                    {item}
                  </span>
                ))}
              </div>
              <dl className="mt-6 flex flex-wrap gap-6 text-sm">
                <div>
                  <dt className="text-canvas/70">Delivery</dt>
                  <dd>Within {offer.terms.delivery_sla_days} days</dd>
                </div>
                <div>
                  <dt className="text-canvas/70">Returns</dt>
                  <dd>{offer.terms.returns_days} days</dd>
                </div>
              </dl>
            </section>

            <section className="rounded-2xl border border-line bg-surface p-6">
              <h2 className="text-lg font-semibold">How this price was found</h2>
              <div className="mt-4 grid gap-5 sm:grid-cols-3">
                <Step title="Merchants bid in secret" body="Each merchant submitted one sealed price for this lot." />
                <Step title="The published rule picked the winner" body="Bids that missed the rules were set aside." />
                <Step
                  title="Your total is within your cap"
                  body={`${formatCents(offer.totals.total_cents)} is at or below your maximum of ${formatCents(
                    offer.totals.cap_cents,
                  )}.`}
                />
              </div>
              {offer.pool_id ? (
                <a
                  className="mt-4 inline-block text-sm font-semibold underline decoration-accent decoration-2 underline-offset-4"
                  href={`/audit/${offer.pool_id}`}
                >
                  See the rules for {offer.pool_title ?? "this pool"}
                </a>
              ) : null}
            </section>

            <section className="rounded-2xl border border-line bg-surface p-6">
              <h2 className="text-lg font-semibold">Shipping address</h2>
              <p className="mt-1 text-sm text-muted">
                Required for delivery. Not sent to PayPal in this build.
              </p>
              <div className="mt-4 grid gap-4 sm:grid-cols-2">
                {ADDRESS_FIELDS.map((field) => (
                  <label
                    key={field.name}
                    className={field.name === "line1" || field.name === "line2" ? "sm:col-span-2" : ""}
                  >
                    <span className="text-sm font-medium">{field.label}</span>
                    <input
                      className="mt-1 w-full rounded-lg border border-line bg-canvas px-3 py-2 text-sm"
                      value={address[field.name]}
                      required={field.required}
                      onChange={(event) =>
                        setAddress((previous) => ({ ...previous, [field.name]: event.target.value }))
                      }
                    />
                  </label>
                ))}
              </div>
            </section>
          </div>

          <aside className="flex h-fit flex-col gap-4 lg:sticky lg:top-6">
            <CountdownCard offer={offer} />
            <div className="rounded-2xl border border-line bg-surface p-6">
              <dl className="space-y-2 text-sm">
                <Row label="Item" value={formatCents(offer.totals.item_cents)} />
                <Row label="Shipping" value={formatCents(offer.totals.shipping_cents)} />
                <Row label="Tax" value={formatCents(offer.totals.tax_cents)} />
              </dl>
              <div className="mt-4 border-t border-line pt-4">
                <p className="text-xs uppercase tracking-label text-muted">Total</p>
                <p className="font-display text-4xl leading-none">{formatCents(offer.totals.total_cents)}</p>
                <p className="mt-1 text-xs text-muted">
                  Your maximum {formatCents(offer.totals.cap_cents)}
                </p>
              </div>
              <p className="mt-4 rounded-lg bg-canvas px-3 py-2 text-xs text-muted">{offer.notices.hold}</p>
              <p className="mt-2 text-xs text-muted">{offer.notices.lots_may_differ}</p>
              <button
                type="button"
                onClick={() => void submit()}
                disabled={expired || submitting}
                className="press mt-4 w-full rounded-xl bg-accent px-5 py-3 text-sm font-semibold text-ink disabled:opacity-50"
              >
                {submitting ? "Opening PayPal…" : "Continue to PayPal"}
              </button>
              <button
                type="button"
                onClick={() => void decline()}
                className="press mt-2 w-full rounded-xl border border-ink px-5 py-3 text-sm font-semibold"
              >
                Decline the offer
              </button>
            </div>
          </aside>
        </div>
      </div>
    </AuthLayout>
  );
}

function CountdownCard({ offer }: { offer: Offer }) {
  const countdown = useCountdown(
    offer.offer_expires_at,
    offer.server_now ?? new Date().toISOString(),
    offer.offer_started_at,
  );
  if (countdown.expired) {
    return (
      <div className="rounded-2xl border border-danger/40 bg-danger-soft p-6 text-center">
        <p className="text-xs uppercase tracking-label text-danger">Expired</p>
        <p className="mt-2 text-lg font-semibold">This offer can no longer be approved.</p>
      </div>
    );
  }
  return (
    <div
      className={`rounded-2xl border p-6 ${countdown.urgent ? "border-danger/40 bg-danger-soft" : "border-line bg-accent-soft"}`}
    >
      <div className="flex items-center gap-4">
        <svg viewBox="0 0 44 44" className="h-14 w-14 -rotate-90" aria-hidden="true">
          <circle cx="22" cy="22" r="18" fill="none" stroke="currentColor" strokeWidth="3" opacity="0.2" />
          <circle
            ref={countdown.ringRef}
            cx="22"
            cy="22"
            r="18"
            fill="none"
            stroke="currentColor"
            strokeWidth="3"
            strokeDasharray={String(2 * Math.PI * 18)}
            strokeDashoffset={String(2 * Math.PI * 18 * (1 - countdown.fractionElapsed))}
            strokeLinecap="round"
          />
        </svg>
        <div>
          <p className="text-xs uppercase tracking-label text-muted">Offer expires in</p>
          <p className="font-mono text-2xl tabular-nums">{countdown.label}</p>
        </div>
      </div>
      <p className="mt-3 text-xs text-muted">If time runs out, your place in this lot ends.</p>
    </div>
  );
}

function Step({ title, body }: { title: string; body: string }) {
  return (
    <div>
      <p className="text-sm font-semibold">{title}</p>
      <p className="mt-1 text-sm text-muted">{body}</p>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between">
      <dt className="text-muted">{label}</dt>
      <dd className="font-medium tabular-nums">{value}</dd>
    </div>
  );
}

function codeOf(failure: unknown): { code: string; message: string } {
  const envelope = failure as { error?: { code?: string; message?: string } } | undefined;
  return {
    code: envelope?.error?.code ?? "REQUEST_FAILED",
    message: envelope?.error?.message ?? "The request could not be completed.",
  };
}
