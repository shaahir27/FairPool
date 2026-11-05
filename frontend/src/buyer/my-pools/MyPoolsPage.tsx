import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { type ApiComponents, envelope, formatDateTime, honestyKinds, HonestyLabels, Icon, Notice, ProductArt, RecordFilters, StatusPill, statusStyle } from "../../shared";
import { loadEntries } from "../prefetch";
import "../settings.css";

type Entry = ApiComponents["schemas"]["MeEntry"];
const REVIEWABLE = new Set(["OFFERED", "ORDER_CREATED"]);
const FINISHED = new Set(["CAPTURED", "REFUNDED", "VOIDED", "EXPIRED", "DECLINED", "REJECTED", "AUTH_FAILED", "CAPTURE_FAILED"]);

function isPast(entry: Entry): boolean {
  return ((!entry.offer || FINISHED.has(entry.offer.status)) && ["CANCELLED", "COMPLETED"].includes(entry.pool_status ?? "")) || entry.entry_status === "WITHDRAWN" || entry.allocation?.status === "PRICED_OUT" || Boolean(entry.offer && FINISHED.has(entry.offer.status));
}
function reviewable(entry: Entry): boolean {
  return !isPast(entry) && Boolean(entry.offer && REVIEWABLE.has(entry.offer.status));
}
function updateFor(entry: Entry): string {
  if (!entry.offer && entry.pool_status === "CANCELLED") return "This pool was cancelled. This entry is no longer participating.";
  if (!entry.offer && entry.pool_status === "COMPLETED") return "This pool has finished. View the pool for its final outcome.";
  if (entry.entry_status === "WITHDRAWN") return "You withdrew from this pool. This entry is no longer participating.";
  if (reviewable(entry)) return "Check the final price and delivery terms before you approve.";
  if (entry.offer) return "View your order for payment and delivery updates.";
  if (entry.allocation?.status === "WAITLISTED") return entry.allocation.waitlist_position !== null
    ? `You're #${entry.allocation.waitlist_position} on the waiting list.`
    : "You're on the waiting list. Your position is not available yet.";
  if (entry.allocation?.status === "PRICED_OUT") return "Your price limit did not qualify for this lot. No seat was assigned.";
  if (entry.allocation?.status === "SEATED") return "You have been allocated a seat. Open the pool to check its current stage.";
  return "Your entry is recorded. Open the pool to see its current stage.";
}

export function MyPoolsPage() {
  const [entries, setEntries] = useState<Entry[] | null>(null);
  const [error, setError] = useState<{code: string; message: string} | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [view, setView] = useState<"current" | "past">("current");
  const [query, setQuery] = useState("");
  useEffect(() => {
    let live = true;
    setError(null);
    void loadEntries(attempt > 0).then(({data, error: failure}) => {
      if (!live) return;
      if (failure || !data) setError(envelope(failure)); else setEntries(data.items);
    }).catch(() => { if (live) setError({code: "REQUEST_FAILED", message: "Check your connection and try again."}); });
    return () => { live = false; };
  }, [attempt]);
  const current = (entries ?? []).filter((entry) => !isPast(entry));
  const past = (entries ?? []).filter(isPast);
  const scoped = view === "current" ? current : past;
  const search = query.trim().toLowerCase();
  const visible = scoped.filter((entry) => !search || [entry.pool_title, entry.product?.title, entry.product?.variant].some((part) => part?.toLowerCase().includes(search)))
    .sort((left, right) => Number(reviewable(right)) - Number(reviewable(left)));
  return <section className="my-pools-page" aria-labelledby="my-pools-title">
    <header className="settings-heading settings-heading-action"><div><h1 id="my-pools-title" className="shop-title">My Pools</h1><p className="shop-copy">Follow your entries, review offers and open your orders.</p></div><Link to="/discover" className="button-secondary">Browse pools<Icon name="arrow" /></Link></header>
    {error ? <Notice kind="error" code={error.code}>{error.message} <button className="signup-back" type="button" onClick={() => setAttempt((value) => value + 1)}>Try again</button></Notice> : null}
    {entries === null ? error ? null : <div role="status" aria-busy="true" aria-label="Loading your pools" className="pool-entry-feed">{[0,1,2].map((index) => <div key={index} className="shop-panel shop-panel-pad"><div className="skeleton h-5 w-1/2" /><div className="skeleton mt-4 h-4 w-2/3" /></div>)}</div>
      : entries.length === 0 ? <div className="pool-list-empty"><Icon name="layers" /><h2>No pools joined yet</h2><p>Choose a pool and set your price limit. Joining is free.</p><Link to="/discover" className="button-primary">Find a pool</Link></div>
      : <><div className="pool-list-controls"><RecordFilters label="Pool history" value={view} onChange={setView} options={[{id: "current", label: "Current pools", count: current.length}, {id: "past", label: "Past entries", count: past.length}]} /><label className="catalogue-search"><Icon name="search" /><span className="sr-only">Search your pools</span><input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search your pools" /></label></div>
        <p className="pool-list-summary" role="status" aria-live="polite">{visible.length} {visible.length === 1 ? "entry" : "entries"}{search ? " match your search" : view === "current" ? " in your current pools" : " in your history"}. {view === "current" && visible.some(reviewable) ? "Offers ready for review appear first." : ""}</p>
        {visible.length === 0 ? <div className="pool-list-empty"><Icon name={search ? "search" : "layers"} /><h2>{search ? "No matching pools" : view === "past" ? "No past entries" : "No current pools"}</h2><p>{search ? "Try another product or pool name." : view === "past" ? "Withdrawn entries and completed offers will appear here." : "Your completed entries are in Past entries. You can also browse a new pool."}</p>{search ? <button className="button-secondary" type="button" onClick={() => setQuery("")}>Clear search</button> : <Link className="button-secondary" to="/discover">Browse pools</Link>}</div>
          : <ul className="pool-entry-feed" aria-label={view === "current" ? "Current pool entries" : "Past pool entries"}>{visible.map((entry) => <EntryCard key={entry.entry_id} entry={entry} />)}</ul>}
      </>}
  </section>;
}

function EntryCard({entry}: {entry: Entry}) {
  const title = entry.product?.title || entry.pool_title || "Your pool entry";
  const shown = entry.entry_status === "WITHDRAWN" ? "WITHDRAWN" : entry.offer?.status ?? (["CANCELLED", "COMPLETED"].includes(entry.pool_status ?? "") ? entry.pool_status : null) ?? entry.allocation?.status ?? entry.entry_status;
  const style = statusStyle(shown);
  const ready = reviewable(entry);
  const destination = ready && entry.offer ? `/offers/${entry.offer.buyer_order_id}` : entry.offer ? `/orders/${entry.offer.buyer_order_id}` : `/pools/${entry.pool_id}`;
  const action = ready ? "Review offer" : entry.offer ? "View order" : "View pool";
  return <li><article className={`pool-entry-card shop-panel shop-panel-pad${ready ? " has-ready-offer" : ""}`} aria-labelledby={`entry-${entry.entry_id}`}>
    <div className="pool-entry-main"><div className="pool-entry-product">
      {entry.product ? <ProductArt title={title} /> : <span className="pool-entry-fallback"><Icon name="layers" /></span>}
      <div><h2 id={`entry-${entry.entry_id}`}>{title}</h2>{entry.pool_title && entry.pool_title !== title ? <p className="shop-copy">{entry.pool_title}</p> : null}{entry.product ? <p className="entry-product-variant">{[entry.product.variant, entry.product.condition.toLowerCase().replaceAll("_", " ")].filter(Boolean).join(", ")}</p> : null}</div>
    </div><div className="pool-entry-state"><StatusPill status={shown} tone={ready ? "active" : style.tone}>{ready ? "Offer ready to review" : style.label}</StatusPill></div></div>
    {entry.labels?.some((label) => label !== "SANDBOX") ? <div className="mt-4"><HonestyLabels kinds={honestyKinds(entry.labels).filter((kind) => kind !== "sandbox")} /></div> : null}
    <div className="pool-entry-next"><p>{updateFor(entry)}</p>{ready && entry.offer ? <p className="pool-offer-deadline"><Icon name="clock" />Review by <time dateTime={entry.offer.offer_expires_at}>{formatDateTime(entry.offer.offer_expires_at)}</time></p> : null}</div>
    <div className="pool-entry-footer"><details className="entry-technical-details"><summary>Entry details</summary><dl><div><dt>Pool reference</dt><dd>{entry.pool_id}</dd></div><div><dt>Entry status</dt><dd>{entry.entry_status}</dd></div>{entry.allocation ? <div><dt>Allocation</dt><dd>{entry.allocation.status}</dd></div> : null}</dl></details><Link to={destination} className={ready ? "button-primary" : "button-secondary"}>{action}<Icon name="arrow" /></Link></div>
  </article></li>;
}
