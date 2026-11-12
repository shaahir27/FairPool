import { type FormEvent, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import {
  api,
  useApiRead,
  type ApiComponents,
  envelope,
  formatCents,
  formatDateTime,
  Icon,
  Notice,
  ProductArt,
  startRouteTransition,
  StatusPill,
  statusStyle,
} from "../../shared";
import { prefetchBuyer } from "../prefetch";
import { rememberPendingRequest } from "../drafts";
import { DemandConsent, FormingDemand } from "../Demand";

type PoolSummary = ApiComponents["schemas"]["PoolSummary"];
type ConfirmationCard = ApiComponents["schemas"]["ConfirmationCard"];
type IntakeTurn = ApiComponents["schemas"]["IntakeMessageResponse"];

/**
 * The badge FR-UI-01 fixes for every pool card. It is the product's promise in one
 * line, so it is written here once and never reworded per screen (I13).
 */
export const JOIN_BADGE =
  "$0 to join. No hold until a merchant meets your price and you approve.";

const PROMPT_LABEL = "What are you looking for and what is your max price?";

/**
 * The server names the manual form in its own instruction; the link follows that
 * wording and is never shown on a question that does not name it (I13).
 */
const NAMES_MANUAL_FORM = /manual form/i;

/** Starting points, not suggestions of a deal: the asks are the buyer's own. */
const EXAMPLE_ASKS = [
  "A 27-inch 4K monitor, matte screen, under $600, delivered to New York",
  "A ceramic kettle for the office, under $80, needed by end of next month",
];

export function DiscoverPage() {
  const requestInput = useRef<HTMLTextAreaElement>(null);
  const navigate = useNavigate();
  const [message, setMessage] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [turn, setTurn] = useState<IntakeTurn | null>(null);
  const [asking, setAsking] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [notice, setNotice] = useState<{ code: string; message: string } | null>(null);
  const [manualPool, setManualPool] = useState("");
  const [demandConsent, setDemandConsent] = useState(false);

  const catalogue = useApiRead("/api/v1/pools?status=OPEN&sort=trending&limit=100",
    (signal) => api.GET("/api/v1/pools", {signal, params: { query: { status: "OPEN", sort: "trending", limit: 100 } }}), {staleTime: 60_000});
  const pools = catalogue.data ?? [];
  const poolsLoading = catalogue.isPending;
  const poolsError = catalogue.error ? "We couldn’t load the open pools. Try again." : "";
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<string>("ALL");

  async function ask(event: FormEvent) {
    event.preventDefault();
    const text = message.trim();
    if (!text || asking) return;
    setAsking(true);
    setNotice(null);
    try {
      const { data, error: failure } = await api.POST("/api/v1/intake/messages", {
        body: { message: text, pool_id: null, session_id: sessionId },
      });
      if (failure || !data) {
        setNotice(envelope(failure));
        return;
      }
      setSessionId(data.session_id);
      setTurn(data);
      setDemandConsent(false);
      if (data.status !== "NO_MATCH") setMessage("");
    } catch {
      setNotice({ code: "REQUEST_FAILED", message: "Check your connection and try again." });
    } finally {
      setAsking(false);
    }
  }

  async function confirm(card: ConfirmationCard) {
    if (confirming) return;
    setConfirming(true);
    setNotice(null);
    try {
      const { data, error: failure } = await api.POST("/api/v1/intake/confirm", {
        body: { proposal_id: card.proposal_id },
      });
      if (failure || !data) {
        setNotice(envelope(failure));
        return;
      }
      // The lobby joins with this id; the request itself is already a server row.
      rememberPendingRequest(card.pool.id, data.confirmed_request_id);
      const lobby = `/pools/${card.pool.id}`;
      startRouteTransition(() => navigate(lobby), "/discover", lobby);
    } catch {
      setNotice({ code: "REQUEST_FAILED", message: "Check your connection and try again." });
    } finally {
      setConfirming(false);
    }
  }

  const card = turn?.status === "READY_TO_CONFIRM" ? (turn.confirmation_card ?? null) : null;
  const search = query.trim().toLocaleLowerCase();
  const categories = Array.from(
    new Map(
      pools.flatMap((pool) => {
        const key = pool.product_key?.split("-")[0]?.trim().toLowerCase();
        return key ? [[key, key.charAt(0).toUpperCase() + key.slice(1)] as const] : [];
      }),
    ).entries(),
  ).sort((a, b) => a[1].localeCompare(b[1]));
  // A refetch can remove the last pool of the selected category; fall back to all.
  const effectiveCategory =
    category === "ALL" || categories.some(([id]) => id === category) ? category : "ALL";
  const visiblePools = pools.filter((pool) => {
    const matchesSearch = [pool.title, pool.variant, pool.condition].some((value) =>
      value?.toLocaleLowerCase().includes(search),
    );
    if (!matchesSearch) return false;
    if (effectiveCategory === "ALL") return true;
    return pool.product_key?.toLocaleLowerCase().split("-")[0] === effectiveCategory;
  });

  return (
    <section aria-labelledby="discover-title" className="discover-page">
      <div className="catalogue" id="open-pools">
        <div className="shop-heading catalogue-heading">
          <div>
            <h1 id="discover-title" className="shop-title">Open pools</h1>
            <p className="shop-copy mt-1" role="status" aria-label="Pool search results" aria-live="polite" aria-atomic="true">
              {poolsLoading
                ? "Loading what is open."
                : poolsError && !catalogue.data
                  ? "Pool availability is unavailable. Reload to try again."
                : search || effectiveCategory !== "ALL"
                  ? `${visiblePools.length} of ${pools.length} pools ${visiblePools.length === 1 ? "matches" : "match"} your search.`
                  : `${pools.length} open ${pools.length === 1 ? "pool" : "pools"} shown, most joined first.`}
            </p>
          </div>
          <div className="discovery-tools"><label className="catalogue-search"><Icon name="search" />
            <span className="sr-only">Search open pools</span>
            <input type="search" value={query} aria-describedby="catalogue-scope" onChange={(event) => setQuery(event.target.value)} placeholder="Search open pools" />
          </label>
          <button type="button" className="button-secondary" onClick={() => requestInput.current?.focus()}>Make a request<Icon name="arrow" /></button></div>
        </div>
        <p id="catalogue-scope" className="catalogue-scope">Search and categories filter the pools shown. Set your delivered-price limit when you join.</p>
        {categories.length > 1 ? (
          <div className="catalogue-category-bar" role="group" aria-label="Filter by category">
            <button
              type="button"
              className={`category-pill-btn ${effectiveCategory === "ALL" ? "is-active" : ""}`}
              aria-pressed={effectiveCategory === "ALL"}
              onClick={() => setCategory("ALL")}
            >
              All pools
            </button>
            {categories.map(([id, label]) => (
              <button
                key={id}
                type="button"
                className={`category-pill-btn ${effectiveCategory === id ? "is-active" : ""}`}
                aria-pressed={effectiveCategory === id}
                onClick={() => setCategory(id)}
              >
                {label}
              </button>
            ))}
          </div>
        ) : null}
        {poolsError ? (
          <div className="mt-4">
            <Notice kind="error">
              {poolsError}{" "}
              <button
                type="button"
                className="signup-back"
                onClick={() => void catalogue.refetch()}
              >
                Reload pools
              </button>
            </Notice>
          </div>
        ) : null}
        {poolsLoading ? (
          <div role="status" aria-busy="true" aria-label="Loading open pools">
            <ul className="catalogue-grid">
              {[0, 1, 2, 3].map((index) => (
                <li key={index} className="shop-panel shop-panel-pad">
                  <div className="skeleton catalogue-loading-art" />
                  <div className="skeleton mt-5 h-5 w-2/3" />
                  <div className="skeleton mt-3 h-4 w-1/2" />
                  <div className="skeleton mt-6 h-9 w-full" />
                </li>
              ))}
            </ul>
          </div>
        ) : poolsError && !catalogue.data ? null : pools.length === 0 ? (
          <p className="shop-copy mt-5">No open pools to join right now.</p>
        ) : visiblePools.length === 0 ? (
          <div className="catalogue-empty"><Icon name="search" /><p>No pools match your search.</p><button type="button" className="button-secondary" onClick={() => { setQuery(""); setCategory("ALL"); }}>Clear search</button></div>
        ) : (
          <ul className="catalogue-grid">
            {visiblePools.map((pool) => (
              <li key={pool.pool_id}>
                <PoolCard pool={pool} />
              </li>
            ))}
          </ul>
        )}
        <p className="catalogue-footnote">Have something in mind already? <Link to="/my-pools">Visit My Pools <Icon name="arrow" /></Link></p>
      </div>
      <FormingDemand />
      <section className="discovery-assistance" aria-labelledby="request-heading">
        <div className="request-introduction">
        <h2 id="request-heading">Make a request</h2>
        <p className="shop-copy">Tell us what you need. We’ll look for a matching open pool.</p>
        <p className="request-hint">Include your budget and delivery location for a more useful match.</p>
        </div>
        <form className="discovery-request" onSubmit={(event) => void ask(event)}>
          <div className="flex flex-wrap items-end gap-3">
            <label className="block min-w-0 flex-1 basis-64">
              <span className="text-sm font-semibold">{PROMPT_LABEL}</span>
              <textarea
                ref={requestInput}
                id="intake-prompt"
                className="form-input prompt-input"
                value={message}
                maxLength={2000}
                rows={2}
                placeholder="For example, a 4K monitor under $600, delivered to New York…"
                onChange={(event) => setMessage(event.target.value)}
              />
            </label>
            <button type="submit" className="button-primary" disabled={asking || !message.trim()}>
              {asking ? "Finding matches…" : "Find matches"}
            </button>
          </div>
          <div className="mt-4 flex flex-wrap items-center gap-2">
            <span className="text-xs text-muted">Try one of these:</span>
            {EXAMPLE_ASKS.map((example, index) => (
              <button
                key={example}
                type="button"
                className="shop-quiet-button"
                disabled={asking}
                onClick={() => { setMessage(example); requestInput.current?.focus(); }}
              >
                {index === 0 ? "Monitor under $600" : "Kettle under $80"}
              </button>
            ))}
          </div>
        </form>

        {notice ? (
          <div className="mt-5">
            <Notice kind="error" code={notice.code}>
              {notice.message}
            </Notice>
          </div>
        ) : null}

        {turn?.status === "NO_MATCH" ? <div className="mt-5">{demandConsent ? <DemandConsent source="intake" onClose={() => setDemandConsent(false)} /> : <button type="button" className="button-secondary" onClick={() => setDemandConsent(true)}>Notify me when a pool forms</button>}</div> : null}
        {turn && !card ? (
          <div className="mt-5">
            {turn.clarifying_question ? (
              <>
                {/* The server's sentence, word for word: it may be a question or the
                    manual-form instruction when AI is off or nothing matched (FR-IN-08). */}
                <Notice kind={turn.status === "NO_MATCH" ? "warn" : "info"}>
                  {turn.clarifying_question}
                </Notice>
                {NAMES_MANUAL_FORM.test(turn.clarifying_question) ? (
                  <div className="manual-entry-choice mt-4">
                    <label htmlFor="manual-pool">Choose a pool for manual entry
                      <select id="manual-pool" className="form-input" value={manualPool} onChange={(event) => setManualPool(event.target.value)}>
                        <option value="">Choose an open pool</option>
                        {pools.map((pool) => <option key={pool.pool_id} value={pool.pool_id}>{pool.title}{pool.variant ? ` · ${pool.variant}` : ""}</option>)}
                      </select>
                    </label>
                    {pools.some((pool) => pool.pool_id === manualPool) ? <Link className="button-secondary" to={`/pools/${manualPool}#pool-entry`}>Fill in my request<Icon name="arrow" /></Link> : null}
                  </div>
                ) : null}
              </>
            ) : (
              <Notice kind="warn">
                No open pool matches that yet. Browse the pools above and state your request in the
                one you want to join.
              </Notice>
            )}
          </div>
        ) : null}

        {card ? (
          <div className="mt-5">
            <ConfirmationCardPanel
              card={card}
              confirming={confirming}
              onConfirm={() => void confirm(card)}
              onRestart={() => {
                setTurn(null);
                setSessionId(null);
              }}
            />
          </div>
        ) : null}

      </section>
    </section>
  );
}

function ConfirmationCardPanel({
  card,
  confirming,
  onConfirm,
  onRestart,
}: {
  card: ConfirmationCard;
  confirming: boolean;
  onConfirm: () => void;
  onRestart: () => void;
}) {
  const firm = card.firm ?? [];
  const preferences = card.preferences ?? [];
  return (
    <section className="shop-panel" aria-labelledby="confirmation-title">
      <div className="panel-band">
        <h2 id="confirmation-title">{card.pool.title}</h2>
        <p className="shop-copy mt-1">
          {[card.pool.variant, card.pool.condition].filter(Boolean).join(" · ")}
        </p>
      </div>
      <div className="shop-panel-pad">
        <p className="shop-copy">
          This is what we understood. Check it before it goes to the merchants.
        </p>
        <dl className="price-rows mt-5">
          <Row label="Deliver to" value={`${card.delivery.region} · ${card.delivery.zone_id}`} />
          <Row label="Needed by" value={card.required_by} />
          <Row label="Latest delivery the pool allows" value={card.pool.latest_delivery} />
          <Row label="Your maximum" value={`${formatCents(card.max_total_cents)} USD`} />
        </dl>
        {firm.length || preferences.length ? (
          <ul className="item-terms mt-4">
            {firm.map((term) => (
              <li key={`firm-${term}`}>
                <Icon name="check" />
                <span>Firm requirement: {term}</span>
              </li>
            ))}
            {preferences.map((term) => (
              <li key={`preference-${term}`}>
                <Icon name="info" />
                <span>Preference: {term}</span>
              </li>
            ))}
          </ul>
        ) : null}
        {/* The notices are the API's own sentences: re-wording them here would be the
            browser making a promise the server did not (FR-UI-08, I13). */}
        <div className="budget-note mt-5">
          <Icon name="shield" />
          <span>{card.notices.no_charge}</span>
        </div>
        <div className="budget-note mt-2">
          <Icon name="info" />
          <span>{card.notices.lots_may_differ}</span>
        </div>
        <div className="mt-6 flex flex-wrap gap-3">
          <button type="button" className="button-primary" disabled={confirming} onClick={onConfirm}>
            {confirming ? "Confirming…" : "Confirm and continue"}
            <Icon name="arrow" />
          </button>
          <button
            type="button"
            className="shop-quiet-button"
            disabled={confirming}
            onClick={onRestart}
          >
            <Icon name="returns" />
            Start over
          </button>
        </div>
      </div>
    </section>
  );
}

function PoolCard({ pool }: { pool: PoolSummary }) {
  const style = statusStyle(pool.status);
  return (
    <article className="catalogue-card" aria-labelledby={`product-${pool.pool_id}`}>
      <div className="catalogue-product">
        <Link className="catalogue-art" to={`/pools/${pool.pool_id}`} onMouseEnter={() => prefetchBuyer(`/pools/${pool.pool_id}`)} onFocus={() => prefetchBuyer(`/pools/${pool.pool_id}`)} onPointerDown={() => prefetchBuyer(`/pools/${pool.pool_id}`)} aria-label={`View ${pool.title}`}>
          <ProductArt title={pool.title} />
          <span className="catalogue-art-caption" aria-label="Category illustration">Illustration</span>
        </Link>
        <div className="catalogue-product-name">
          <h2 id={`product-${pool.pool_id}`}>
            <Link to={`/pools/${pool.pool_id}`} onMouseEnter={() => prefetchBuyer(`/pools/${pool.pool_id}`)} onFocus={() => prefetchBuyer(`/pools/${pool.pool_id}`)}>{pool.title}</Link>
          </h2>
          {pool.variant ? <p className="catalogue-variant">{pool.variant}</p> : null}
          <div className="catalogue-card-badge-row">
            <StatusPill status={pool.status} tone={style.tone}>
              {style.label === pool.status ? pool.status.charAt(0) + pool.status.slice(1).toLowerCase() : style.label}
            </StatusPill>
            {pool.condition ? <span className="pool-condition-badge">{pool.condition.toLowerCase().replaceAll("_", " ")}</span> : null}
          </div>
        </div>
      </div>
      <div className="catalogue-card-body">
        <p className="catalogue-price">Price set after bidding
          <span>You choose your maximum before joining.</span>
        </p>
        <dl className="pool-participation" aria-label="Pool participation">
          {pool.entry_count != null ? <div><dt>Recorded demand</dt><dd>{pool.entry_count.toLocaleString("en-US")} {pool.entry_count === 1 ? "entry" : "entries"}</dd></div> : null}
          <div><dt>Pool capacity</dt><dd>{pool.seats} places</dd></div>
          <div><dt>Pool minimum</dt><dd>{pool.min_seats} buyers</dd></div>
        </dl>
        <dl className="catalogue-terms" aria-label="Delivery and returns">
          <div className="catalogue-delivery-area"><dt>{pool.delivery_regions?.length ? "Delivery areas" : "Delivery zones"}</dt><dd>{pool.delivery_regions?.length ? pool.delivery_regions.join(", ") : pool.zone_ids.join(", ") || "Not published"}</dd></div>
          {typeof pool.delivery_sla_days === "number" ? <div><dt>Delivery requirement</dt><dd>Within {pool.delivery_sla_days} days</dd></div> : null}
          {typeof pool.min_return_days === "number" ? <div><dt>Minimum returns</dt><dd>{pool.min_return_days} days</dd></div> : null}
        </dl>
        {pool.bundle_contents?.length ? <details className="catalogue-included"><summary>Included items</summary><p>{pool.bundle_contents.join(", ")}</p></details> : null}
      </div>
      <div className="catalogue-card-footer">
        <p className="catalogue-deadline">
          {pool.close_at ? (
            <>
              <span>Entries close</span>
              <time dateTime={pool.close_at}>
                {formatDateTime(pool.close_at)}
              </time>
            </>
          ) : (
            "Closing time not published"
          )}
        </p>
        <Link className="button-primary" to={`/pools/${pool.pool_id}`} onMouseEnter={() => prefetchBuyer(`/pools/${pool.pool_id}`)} onFocus={() => prefetchBuyer(`/pools/${pool.pool_id}`)} onPointerDown={() => prefetchBuyer(`/pools/${pool.pool_id}`)}>
          View pool<Icon name="arrow" />
        </Link>
      </div>
      <p className="catalogue-promise"><Icon name="shield" /><span>{JOIN_BADGE}</span></p>
    </article>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}
