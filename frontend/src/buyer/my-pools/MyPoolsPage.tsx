import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { OfferCheckout } from "../../checkout";
import { type ApiComponents, Icon, Notice, StatusPill, statusStyle } from "../../shared";
import { loadEntries } from "../prefetch";

type MeEntry = ApiComponents["schemas"]["MeEntry"];
type GroupId = "pending" | "waitlist" | "action";

const GROUPS: readonly {
  id: GroupId;
  title: string;
  note: string;
  empty: string;
}[] = [
  {
    id: "pending",
    title: "Pending",
    note: "Entries with nothing to approve right now.",
    empty: "No entries are waiting for a seat.",
  },
  {
    id: "waitlist",
    title: "Waitlist",
    note: "Entries waiting for a seat to open.",
    empty: "No entries are on a waitlist.",
  },
  {
    id: "action",
    title: "Action required",
    note: "Offers waiting for your approval.",
    empty: "No offers are waiting for you.",
  },
];

/**
 * FR-UI-02: only an offer still waiting on the buyer is Action required.
 * `/me/entries` also returns offers that have moved past approval (CAPTURED,
 * REFUNDING, ...); those entries have nothing to approve and belong in Pending,
 * where a short line links to their order. PRICED_OUT has no offer at all.
 */
const LIVE_OFFER = new Set(["OFFERED", "ORDER_CREATED"]);

function hasLiveOffer(entry: MeEntry): boolean {
  return Boolean(entry.offer && LIVE_OFFER.has(entry.offer.status));
}

function groupOf(entry: MeEntry): GroupId {
  if (hasLiveOffer(entry)) return "action";
  if (entry.allocation?.status === "WAITLISTED") return "waitlist";
  return "pending";
}

function envelope(failure: unknown): { code: string; message: string } {
  const value = failure as { error?: { code?: string; message?: string } } | undefined;
  return {
    code: value?.error?.code ?? "REQUEST_FAILED",
    message: value?.error?.message ?? "The request could not be completed.",
  };
}

export function MyPoolsPage() {
  const [entries, setEntries] = useState<MeEntry[] | null>(null);
  const [error, setError] = useState<{ code: string; message: string } | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let live = true;
    setError(null);
    void loadEntries(attempt > 0)
      .then(({ data, error: failure }) => {
        if (!live) return;
        if (failure || !data) setError(envelope(failure));
        else setEntries(data.items);
      })
      .catch(() => {
        if (live) setError({ code: "REQUEST_FAILED", message: "Check your connection and try again." });
      });
    return () => {
      live = false;
    };
  }, [attempt]);

  const pools = new Set((entries ?? []).map((entry) => entry.pool_id)).size;
  return (
    <section aria-labelledby="my-pools-title" className="mx-auto w-full max-w-[1100px]">
      <div className="shop-heading">
        <h1 id="my-pools-title" className="shop-title">
          My Pools
        </h1>
        <p className="shop-copy mt-1" role="status" aria-live="polite" aria-atomic="true">
          {entries === null
            ? error
              ? "Your entries could not be loaded."
              : "Loading your entries."
            : `${entries.length} ${entries.length === 1 ? "entry" : "entries"} across ${pools} ${pools === 1 ? "pool" : "pools"}.`}
        </p>
      </div>

      {error ? (
        <div className="mb-6">
          <Notice kind="error" code={error.code}>
            {error.message}{" "}
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

      {entries === null ? (
        error ? null : (
          <div role="status" aria-busy="true" aria-label="Loading your entries" className="grid gap-8">
            {[0, 1].map((index) => (
              <div key={index}>
                <div className="skeleton h-6 w-40" />
                <div className="mt-4 grid gap-4 md:grid-cols-2">
                  {[0, 1].map((card) => (
                    <div key={card} className="shop-panel shop-panel-pad">
                      <div className="skeleton h-4 w-1/3" />
                      <div className="skeleton mt-4 h-5 w-2/3" />
                      <div className="skeleton mt-5 h-10 w-full" />
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )
      ) : entries.length === 0 ? (
        <section className="panel" aria-labelledby="my-pools-empty">
          <h2 id="my-pools-empty">No entries yet</h2>
          <p className="shop-copy mt-2">
            Joining is free and places no hold. You approve your own offer before any payment.
          </p>
          <Link className="button-secondary mt-5" to="/discover">
            Find an open pool
            <Icon name="arrow" />
          </Link>
        </section>
      ) : (
        <div className="grid gap-10">
          {GROUPS.map((group) => {
            const grouped = entries.filter((entry) => groupOf(entry) === group.id);
            return (
              <section key={group.id} aria-labelledby={`my-pools-${group.id}`} className="enter-rise">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <h2 id={`my-pools-${group.id}`} className="text-lg font-semibold tracking-[-.02em]">
                    {group.title}
                  </h2>
                  <span className="text-xs text-muted">
                    {grouped.length} {grouped.length === 1 ? "entry" : "entries"}
                  </span>
                </div>
                <p className="shop-copy mt-1">{group.note}</p>
                {grouped.length === 0 ? (
                  <p className="shop-copy mt-3">{group.empty}</p>
                ) : (
                  <ul className={group.id === "action" ? "mt-4 grid gap-4" : "mt-4 grid gap-4 md:grid-cols-2"}>
                    {grouped.map((entry) =>
                      hasLiveOffer(entry) && entry.offer ? (
                        <li key={entry.entry_id} className="min-w-0">
                          <OfferCheckout
                            buyerOrderId={entry.offer.buyer_order_id}
                            onChanged={() => setAttempt((value) => value + 1)}
                          />
                        </li>
                      ) : (
                        <EntryCard key={entry.entry_id} entry={entry} />
                      ),
                    )}
                  </ul>
                )}
              </section>
            );
          })}
        </div>
      )}
    </section>
  );
}

function EntryCard({ entry }: { entry: MeEntry }) {
  // The allocation is what places the buyer; the entry's own state is shown next
  // to it so neither value is replaced by a friendlier word (FR-UI-08).
  const shown = entry.allocation?.status ?? entry.entry_status;
  const style = statusStyle(shown);
  const headingId = `my-pools-entry-${entry.entry_id}`;
  return (
    <li className="min-w-0">
      <article className="shop-panel shop-panel-pad" aria-labelledby={headingId}>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-xs font-medium text-muted">Pool</p>
            <p id={headingId} className="mt-1 break-all font-mono text-xs text-muted">
              {entry.pool_id}
            </p>
          </div>
          <StatusPill status={shown} tone={style.tone}>
            {style.label}
          </StatusPill>
        </div>
        <p className="shop-copy mt-3">{entryLine(entry)}</p>
        {entry.offer ? <OfferMovedOn offer={entry.offer} /> : null}
        <p className="mt-2 text-xs text-muted">
          Entry status <code className="font-mono">{entry.entry_status}</code>
        </p>
        <Link
          className="signup-back mt-4 inline-flex min-h-[44px] items-center gap-2"
          to={`/pools/${entry.pool_id}`}
        >
          Open pool lobby for {entry.pool_id}
          <Icon name="arrow" />
        </Link>
      </article>
    </li>
  );
}

/**
 * An offer past approval is not an action: one line states the API status and
 * links to the order that owns the rest of the story.
 */
function OfferMovedOn({ offer }: { offer: NonNullable<MeEntry["offer"]> }) {
  const style = statusStyle(offer.status);
  return (
    <p className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1">
      <StatusPill status={offer.status} tone={style.tone}>
        {style.label}
      </StatusPill>
      <Link
        className="signup-back inline-flex min-h-[44px] items-center gap-2"
        to={`/orders/${offer.buyer_order_id}`}
      >
        Open order for {offer.buyer_order_id}
        <Icon name="arrow" />
      </Link>
    </p>
  );
}

function entryLine(entry: MeEntry): string {
  // EntryCard only renders for offers past approval; a live offer gets the checkout card.
  if (entry.offer) return "This entry's offer has moved past approval.";
  const allocation = entry.allocation;
  if (allocation?.status === "WAITLISTED") {
    return `Waitlisted, position #${allocation.waitlist_position ?? allocation.rank}`;
  }
  if (allocation?.status === "PRICED_OUT") {
    return "Priced out of this lot. No seat was allocated to this entry.";
  }
  if (allocation?.status === "SEATED") {
    return "Seat allocated. No live offer is attached to this entry.";
  }
  if (allocation) return `Allocation ${allocation.status}.`;
  return "No seat allocation yet.";
}
