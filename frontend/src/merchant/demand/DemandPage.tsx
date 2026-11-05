import { useEffect, useState } from "react";

import {
  api,
  type ApiComponents,
  formatDateTime,
  Icon,
  Notice,
  ProductArt,
  StatusPill,
  useCountdown,
} from "../../shared";
import { failureEnvelope, productName, useMerchantEvents } from "../lib";

import { BidComposer } from "./BidComposer";

type LotSummary = ApiComponents["schemas"]["MerchantLotSummary"];

/**
 * FR-UI-04: lots in BIDDING with the requirement the merchant prices against.
 * Search is local over the loaded answer, exactly as the buyer catalogue does;
 * the backend's semantic `q` is a retrieval aid, not a replacement for typing.
 */
export function DemandPage() {
  const [query, setQuery] = useState("");
  const [lots, setLots] = useState<LotSummary[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<{ code: string; message: string } | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [serverNow, setServerNow] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    setLoading(true);
    void api
      .GET("/api/v1/merchant/lots")
      .then(({ data, error: failure }) => {
        if (!live) return;
        if (failure || !data) {
          setError(failureEnvelope(failure));
          setLots([]);
          return;
        }
        setLots(Array.isArray(data) ? data : []);
        setError(null);
      })
      .catch(() => {
        if (live) {
          setError({
            code: "REQUEST_FAILED",
            message: "Check your connection, then reload the lots.",
          });
          setLots([]);
        }
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
    };
  }, [attempt]);

  useMerchantEvents((event) => {
    // The feed accelerates the screen; the JSON refetch above is still the truth.
    if (event.server_time) setServerNow(event.server_time);
    if (event.type !== "tick") setAttempt((value) => value + 1);
  });

  const search = query.trim().toLocaleLowerCase();
  const loaded = lots ?? [];
  const visible = loaded.filter((lot) =>
    [lot.product_key, lot.variant, lot.condition, lot.zone_id].some((value) =>
      value?.toLocaleLowerCase().includes(search),
    ),
  );
  const selected = loaded.find((lot) => lot.lot_id === selectedId) ?? null;

  return (
    <div className="merchant-page">
      <header className="merchant-heading">
        <div>
          <h1 className="shop-title">Demand Board</h1>
          <p className="shop-copy mt-2">
            Open lots taking sealed bids. Your price, terms and capacity are fixed in
            the revision you confirm.
          </p>
        </div>
        <label className="catalogue-search">
          <Icon name="search" />
          <span className="sr-only">Search open lots</span>
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search open lots"
          />
        </label>
      </header>

      <p
        className="shop-copy"
        role="status"
        aria-label="Lot search results"
        aria-live="polite"
        aria-atomic="true"
      >
        {loading
          ? "Loading open lots."
          : search
            ? `${visible.length} of ${loaded.length} ${loaded.length === 1 ? "lot" : "lots"} ${visible.length === 1 ? "matches" : "match"} your search.`
            : `${loaded.length} ${loaded.length === 1 ? "lot is" : "lots are"} open for bidding.`}
      </p>

      {error ? (
        <Notice kind="error" code={error.code}>
          {error.message}{" "}
          <button type="button" className="merchant-link" onClick={() => setAttempt((value) => value + 1)}>
            Reload lots
          </button>
        </Notice>
      ) : null}

      {loading ? (
        <div role="status" aria-busy="true" aria-label="Loading open lots">
          <ul className="merchant-lot-list">
            {[0, 1, 2].map((index) => (
              <li key={index} className="shop-panel shop-panel-pad">
                <div className="skeleton h-5 w-1/2" />
                <div className="skeleton mt-3 h-4 w-2/3" />
                <div className="skeleton mt-4 h-9 w-40" />
              </li>
            ))}
          </ul>
        </div>
      ) : loaded.length === 0 && !error ? (
        <div className="catalogue-empty">
          <Icon name="layers" />
          <p>No lots are open for bidding right now.</p>
        </div>
      ) : visible.length === 0 ? (
        <div className="catalogue-empty">
          <Icon name="search" />
          <p>No lots match your search.</p>
          <button type="button" className="button-secondary" onClick={() => setQuery("")}>
            Clear search
          </button>
        </div>
      ) : (
        <ul className="merchant-lot-list" aria-label="Lots open for bidding">
          {visible.map((lot) => (
            <li key={lot.lot_id}>
              <article className="merchant-lot">
                <div className="merchant-lot-art">
                  <ProductArt title={lot.product_key} />
                </div>
                <div className="merchant-lot-body">
                  <div className="merchant-lot-title">
                    <h2>{productName(lot.product_key)}</h2>
                    <StatusPill status={lot.status} tone="pending" />
                  </div>
                  <p className="shop-copy">
                    <code className="merchant-code">{lot.product_key}</code>
                    {lot.variant || lot.condition
                      ? ` · ${[lot.variant, lot.condition].filter(Boolean).join(" · ")}`
                      : null}
                  </p>
                  <dl className="merchant-facts">
                    <div>
                      <dt>Lot</dt>
                      <dd>
                        {lot.seats} seats · minimum {lot.min_seats}
                      </dd>
                    </div>
                    <div>
                      <dt>Zone</dt>
                      <dd>{lot.zone_id}</dd>
                    </div>
                    <div>
                      <dt>Delivery</dt>
                      <dd>within {lot.delivery_sla_days} days</dd>
                    </div>
                    <div>
                      <dt>Returns</dt>
                      <dd>at least {lot.min_return_days} days</dd>
                    </div>
                    <div>
                      <dt>Bid deadline</dt>
                      <dd>
                        <Deadline lot={lot} serverNow={serverNow} />
                      </dd>
                    </div>
                  </dl>
                </div>
                <div className="merchant-lot-actions">
                  <button
                    type="button"
                    className="button-secondary"
                    aria-expanded={selectedId === lot.lot_id}
                    onClick={() => setSelectedId(lot.lot_id)}
                  >
                    Prepare a bid
                  </button>
                </div>
              </article>
            </li>
          ))}
        </ul>
      )}

      {selected ? (
        <BidComposer key={selected.lot_id} lot={selected} />
      ) : null}
    </div>
  );
}

function Deadline({ lot, serverNow }: { lot: LotSummary; serverNow: string | null }) {
  if (!lot.bid_close_at) return <span>Not published</span>;
  return (
    <>
      <time dateTime={lot.bid_close_at}>{formatDateTime(lot.bid_close_at)}</time>
      {serverNow ? <CountdownLabel expiresAt={lot.bid_close_at} serverNow={serverNow} /> : null}
    </>
  );
}

function CountdownLabel({ expiresAt, serverNow }: { expiresAt: string; serverNow: string }) {
  const countdown = useCountdown(expiresAt, serverNow);
  return (
    <span className="merchant-countdown">
      {" "}
      · {countdown.expired ? "deadline reached" : `${countdown.label} left`}
    </span>
  );
}
