import { useState } from "react";
import { Link } from "react-router-dom";

import {
  api,
  useApiRead,
  type ApiComponents,
  Icon,
  Notice,
  RecordFilters,
  REJECT_REASON_LABELS,
  StatusPill,
} from "../../shared";
import { failureEnvelope, productName, shortId, useMerchantEvents } from "../lib";

import { CheckoutTracker } from "./CheckoutTracker";
import { bidGroup, type BidSection } from "./tracker";

type BidView = ApiComponents["schemas"]["BidView"];

const SECTIONS: ReadonlyArray<{ id: BidSection; title: string }> = [
  { id: "pending", title: "Pending" },
  { id: "checkout", title: "In Checkout" },
  { id: "lost", title: "Lost or Failed" },
];

/**
 * FR-UI-05: the merchant's own bids, grouped by where they stand. The list route
 * already filters by merchant; this screen never adds an identity of its own.
 */
export function BidsPage() {
  const [filter, setFilter] = useState<BidSection | "all">("all");
  const records = useApiRead("/api/v1/merchant/bids", (signal) => api.GET("/api/v1/merchant/bids", {signal}));
  const bids: BidView[] | null = records.data?.items ?? null;
  const loading = records.isPending;
  const error = records.error ? failureEnvelope(records.error) : null;
  const [serverNow, setServerNow] = useState<string | null>(null);

  useMerchantEvents((event) => {
    if (event.server_time) setServerNow(event.server_time);
    if (event.type === "bid_status" || event.type === "checkout_progress" || event.type === "lot_open") {
      void records.refetch();
    }
  });

  const loaded = bids ?? [];
  const grouped: Record<BidSection, BidView[]> = { pending: [], checkout: [], lost: [] };
  for (const bid of loaded) grouped[bidGroup(bid.status)].push(bid);

  return (
    <div className="merchant-page">
      <header className="merchant-heading">
        <div>
          <h1 className="shop-title">Active Bids</h1>
          <p className="shop-copy mt-2">
            Only bids from your merchant account appear here. Holds and captures are
            counts from the awarded lot, never buyer identities.
          </p>
        </div>
        <button
          type="button"
          className="shop-quiet-button"
          onClick={() => void records.refetch()}
        >
          <Icon name="returns" />
          Refresh bids
        </button>
      </header>

      {bids && bids.length > 0 ? <RecordFilters label="Filter your bids" value={filter} onChange={setFilter} options={[
        {id: "all", label: "All bids", count: bids.length},
        ...SECTIONS.map((section) => ({id: section.id, label: section.title, count: grouped[section.id].length})),
      ]} /> : null}
      {error ? (
        <Notice kind="error" code={error.code}>
          {error.message}{" "}
          <button type="button" className="merchant-link" onClick={() => void records.refetch()}>
            Reload bids
          </button>
        </Notice>
      ) : null}

      {loading && bids === null ? (
        <div role="status" aria-busy="true" aria-label="Loading your bids">
          <div className="merchant-lot-list">
            {[0, 1, 2].map((index) => (
              <div key={index} className="shop-panel shop-panel-pad">
                <div className="skeleton h-5 w-1/3" />
                <div className="skeleton mt-3 h-4 w-2/3" />
              </div>
            ))}
          </div>
        </div>
      ) : loaded.length === 0 && !error ? (
        <div className="catalogue-empty">
          <Icon name="layers" />
          <p>No bids from your merchant account yet.</p>
          <Link className="button-secondary" to="/merchant/demand">
            Open the Demand Board
          </Link>
        </div>
      ) : (
        <div className="merchant-bid-sections">
          {SECTIONS.filter((section) => filter === "all" || filter === section.id).map((section) => {
            const items = grouped[section.id];
            return (
              <section
                key={section.id}
                className="merchant-bid-section"
                aria-labelledby={`bids-${section.id}-title`}
              >
                <div className="merchant-section-heading">
                  <h2 id={`bids-${section.id}-title`}>{section.title}</h2>
                  <span className="shop-copy">
                    {items.length} {items.length === 1 ? "bid" : "bids"}
                  </span>
                </div>
                {items.length === 0 ? (
                  <p className="merchant-empty">No bids in this section.</p>
                ) : (
                  <ul className="merchant-bid-list">
                    {items.map((bid) => (
                      <li key={bid.bid_id}>
                        <BidCard bid={bid} section={section.id} serverNow={serverNow} />
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            );
          })}
        </div>
      )}
    </div>
  );
}

function BidCard({
  bid,
  section,
  serverNow,
}: {
  bid: BidView;
  section: BidSection;
  serverNow: string | null;
}) {
  const structured = bid.structured ?? null;
  const key =
    typeof structured?.product_key === "string" && structured.product_key.trim()
      ? structured.product_key
      : null;
  const flags = bid.flags ?? [];
  const reason = bid.reject_reason ?? null;
  const tone = section === "checkout" ? "active" : section === "lost" ? "bad" : "pending";

  return (
    <article className="merchant-bid">
      <div className="merchant-bid-head">
        <div className="merchant-bid-identity">
          <h3>{productName(key ?? `Bid ${shortId(bid.bid_id)}`)}</h3>
          <p className="shop-copy">
            {key ? <code className="merchant-code">{key}</code> : null}
            {" Â· "}Lot {shortId(bid.lot_id)} Â· revision {bid.current_revision}
          </p>
        </div>
        <StatusPill status={bid.status} tone={tone}>
          {bid.status}
        </StatusPill>
      </div>

      {flags.length > 0 ? (
        <ul className="merchant-flags" aria-label="Bid flags">
          {flags.map((flag) => (
            <li key={`${flag.code}-${flag.field}`}>
              <strong>{flag.evidence}</strong>{" "}
              <span>{flag.field.replaceAll("_", " ")}</span>{" "}
              <code className="merchant-code">{flag.code}</code>{" "}
              <span className="merchant-flag-severity">{flag.severity}</span>
            </li>
          ))}
        </ul>
      ) : null}

      {reason ? (
        <p className="merchant-reject">
          <span className="merchant-label">Reason</span>{" "}
          <code className="merchant-code">{reason}</code>{" "}
          <span>
            {REJECT_REASON_LABELS[reason] ??
              "The API did not publish a description for this reason code."}
          </span>
        </p>
      ) : null}

      {section === "checkout" ? (
        <CheckoutTracker lotId={bid.lot_id} serverNow={serverNow} />
      ) : null}
    </article>
  );
}
