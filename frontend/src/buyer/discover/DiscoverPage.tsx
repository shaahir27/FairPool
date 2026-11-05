import { type FormEvent, useState } from "react";
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
  const navigate = useNavigate();
  const [message, setMessage] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [turn, setTurn] = useState<IntakeTurn | null>(null);
  const [asking, setAsking] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [notice, setNotice] = useState<{ code: string; message: string } | null>(null);

  const catalogue = useApiRead("/api/v1/pools?status=OPEN&sort=trending",
    (signal) => api.GET("/api/v1/pools", {signal, params: { query: { status: "OPEN", sort: "trending" } }}), {staleTime: 60_000});
  const pools = catalogue.data ?? [];
  const poolsLoading = catalogue.isPending;
  const poolsError = catalogue.error ? "We couldn’t load the open pools. Try again." : "";
  const [query, setQuery] = useState("");

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
      setMessage("");
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
  const visiblePools = pools.filter((pool) =>
    [pool.title, pool.variant, pool.condition].some((value) => value?.toLocaleLowerCase().includes(search)),
  );

  return (
    <section aria-labelledby="discover-title" className="discover-page">
      <div className="catalogue" id="open-pools">
        <div className="shop-heading catalogue-heading">
          <div>
            <h1 id="discover-title" className="shop-title">Open pools</h1>
            <p className="shop-copy mt-1" role="status" aria-label="Pool search results" aria-live="polite" aria-atomic="true">
              {poolsLoading
                ? "Loading what is open."
                : search
                  ? `${visiblePools.length} of ${pools.length} pools ${visiblePools.length === 1 ? "matches" : "match"} your search.`
                  : `${pools.length} ${pools.length === 1 ? "pool is" : "pools are"} open, most joined first.`}
            </p>
          </div>
          <label className="catalogue-search"><Icon name="search" />
            <span className="sr-only">Search open pools</span>
            <input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search open pools" />
          </label>
        </div>
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
        ) : pools.length === 0 ? (
          <p className="shop-copy mt-5">No open pools to join right now.</p>
        ) : visiblePools.length === 0 ? (
          <div className="catalogue-empty"><Icon name="search" /><p>No pools match your search.</p><button type="button" className="button-secondary" onClick={() => setQuery("")}>Clear search</button></div>
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
                id="intake-prompt"
                className="form-input prompt-input"
                value={message}
                maxLength={2000}
                rows={2}
                placeholder="For example, a 4K monitor under $600, delivered to New York…"
                onChange={(event) => setMessage(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    event.currentTarget.form?.requestSubmit();
                  }
                }}
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
                onClick={() => setMessage(example)}
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
                  <a
                    className="signup-back mt-2 inline-flex min-h-[44px] items-center gap-2 font-semibold"
                    href="#open-pools"
                  >
                    Browse the open pools to use the manual form
                    <Icon name="arrow" />
                  </a>
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
    <article className="catalogue-card">
      <Link className="catalogue-art" to={`/pools/${pool.pool_id}`} onMouseEnter={() => prefetchBuyer(`/pools/${pool.pool_id}`)} onFocus={() => prefetchBuyer(`/pools/${pool.pool_id}`)} onPointerDown={() => prefetchBuyer(`/pools/${pool.pool_id}`)} aria-label={`View ${pool.title}`}>
        <ProductArt title={pool.title} />
        <span className="catalogue-art-caption">Category illustration</span>
      </Link>
      <div className="catalogue-card-body">
        <div className="flex items-start justify-between gap-3">
          <h2 className="min-w-0 text-[17px] font-semibold leading-snug tracking-[-.025em]">
            {pool.title}
          </h2>
          <StatusPill status={pool.status} tone={style.tone}>
            {style.label}
          </StatusPill>
        </div>
        <p className="shop-copy mt-2">
          {[pool.condition?.replaceAll("_", " "), pool.variant]
            .filter(Boolean)
            .join(" · ")}
        </p>
        <div className="catalogue-facts"><span><Icon name="layers" />{pool.seats} seats · minimum {pool.min_seats}</span></div>
        <p className="catalogue-deadline">
          {pool.close_at ? (
            <>
              Entries close{" "}
              <time dateTime={pool.close_at} className="font-medium text-ink">
                {formatDateTime(pool.close_at)}
              </time>
            </>
          ) : (
            "Closing time not published"
          )}
        </p>
        <p className="catalogue-price">Price set after bidding<span>You choose your maximum before joining.</span></p>
        <p className="catalogue-promise">
          <Icon name="shield" className="mt-px" />
          <span>{JOIN_BADGE}</span>
        </p>
      </div>
      <div className="catalogue-card-footer">
        <Link className="catalogue-link" to={`/pools/${pool.pool_id}`} onMouseEnter={() => prefetchBuyer(`/pools/${pool.pool_id}`)} onFocus={() => prefetchBuyer(`/pools/${pool.pool_id}`)} onPointerDown={() => prefetchBuyer(`/pools/${pool.pool_id}`)}>
          Open the pool
          <Icon name="arrow" />
        </Link>
      </div>
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
