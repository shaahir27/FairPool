import { type FormEvent, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import {
  API_BASE_URL,
  api,
  type ApiComponents,
  formatDateTime,
  HonestyLabels,
  Icon,
  Notice,
  ProductArt,
  StatusPill,
  statusStyle,
  useCountdown,
} from "../../shared";
import { JOIN_BADGE } from "../discover/DiscoverPage";
import {
  clearPendingRequest,
  readPendingRequest,
  rememberPendingRequest,
} from "../drafts";
import { EntryReceiptPage } from "../receipt/EntryReceiptPage";
import { usdToCents } from "./money";

type PoolDetail = ApiComponents["schemas"]["PoolDetail"];
type EntryStatus = ApiComponents["schemas"]["EntryStatusResponse"];

function envelope(failure: unknown): { code: string; message: string } {
  const value = failure as { error?: { code?: string; message?: string } } | undefined;
  return {
    code: value?.error?.code ?? "REQUEST_FAILED",
    message: value?.error?.message ?? "The request could not be completed.",
  };
}

function text(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function number(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function record(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

/** The regions a pool actually accepts, read out of its frozen template. */
function deliveryRegions(template: PoolDetail["template"]): string[] {
  const zones = Array.isArray(template.zones) ? (template.zones as unknown[]) : [];
  const regions: string[] = [];
  for (const zone of zones) {
    const listed = record(zone)?.regions;
    if (!Array.isArray(listed)) continue;
    for (const item of listed as unknown[]) {
      const value = text(item);
      if (value) regions.push(value);
    }
  }
  return regions;
}

function windowLabel(seconds: number): string {
  if (seconds < 60) return `${seconds} seconds`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} minutes`;
  return `${Math.round(seconds / 3600)} hours`;
}

/**
 * The pool's own stages, read straight out of the PS transitions
 * (`state-machines.md`): entries, the seeded draw, the lots and their offers, the end.
 * Nothing here is inferred from a deadline the browser guessed.
 */
const STAGES: readonly { label: string; note: string; states: readonly string[] }[] = [
  {
    label: "Entries open",
    note: "Join for free, withdraw any time before the window closes.",
    states: ["PUBLISHED", "OPEN"],
  },
  {
    label: "Fair draw",
    note: "Commitments are published before the seed exists, then the order is computed.",
    states: ["CLOSED", "SEEDED"],
  },
  {
    label: "Lots and offers",
    note: "Merchants bid sealed; seats get their own offer to approve.",
    states: ["ALLOCATED", "RUNNING"],
  },
  {
    label: "Pool complete",
    note: "Every lot has reached an outcome: funded, or closed at net zero.",
    states: ["COMPLETED"],
  },
];

function stageIndex(status: string): number {
  const index = STAGES.findIndex((stage) => stage.states.includes(status));
  return index === -1 ? 0 : index;
}

export function PoolPage() {
  const { poolId } = useParams<{ poolId: string }>();
  const [detail, setDetail] = useState<PoolDetail | null>(null);
  const [loadError, setLoadError] = useState<{ code: string; message: string } | null>(null);
  const [missing, setMissing] = useState(false);
  const [attempt, setAttempt] = useState(0);

  const [entry, setEntry] = useState<EntryStatus | null>(null);
  const [entryRevision, setEntryRevision] = useState(0);
  const [entryPoolId, setEntryPoolId] = useState<string | null>(null);
  const [entryError, setEntryError] = useState(false);
  const [serverNow, setServerNow] = useState<string | null>(null);
  const [liveStatus, setLiveStatus] = useState<string | null>(null);
  const [liveLots, setLiveLots] = useState<Record<string, string>>({});

  const [showReceipt, setShowReceipt] = useState(false);
  const [pending, setPending] = useState<string | null>(null);

  useEffect(() => {
    if (!poolId) return;
    let live = true;
    setDetail(null);
    setLoadError(null);
    setMissing(false);
    setLiveStatus(null);
    setLiveLots({});
    void api
      .GET("/api/v1/pools/{pool_id}", { params: { path: { pool_id: poolId } } })
      .then(({ data, error: failure }) => {
        if (!live) return;
        if (failure || !data) {
          const value = envelope(failure);
          if (value.code === "NOT_FOUND") setMissing(true);
          else setLoadError(value);
          return;
        }
        setDetail(data);
      })
      .catch(() => {
        if (live) {
          setLoadError({ code: "REQUEST_FAILED", message: "Check your connection and try again." });
        }
      });
    return () => {
      live = false;
    };
  }, [poolId, attempt]);

  useEffect(() => {
    if (!poolId) return;
    let live = true;
    setEntryPoolId(null);
    setEntryError(false);
    setPending(readPendingRequest(poolId));
    void api
      .GET("/api/v1/pools/{pool_id}/entries/me", { params: { path: { pool_id: poolId } } })
      .then(({ data, error: failure, response }) => {
        if (!live) return;
        // 404 is the honest answer for "you have no entry here", not a failed load.
        const absent = response?.status === 404 || envelope(failure).code === "NOT_FOUND";
        if (data && !failure) setEntry(data);
        else if (absent) setEntry(null);
        else setEntryError(true);
      })
      .catch(() => {
        if (live) setEntryError(true);
      })
      .finally(() => {
        if (live) setEntryPoolId(poolId);
      });
    return () => {
      live = false;
    };
  }, [poolId, attempt, entryRevision]);

  useEffect(() => {
    if (!poolId || typeof EventSource !== "function") return;
    // OpenAPI types this feed `application/json` because the document has no SSE
    // response, so it is read with EventSource against the API origin, not the fetch client.
    const source = new EventSource(`${API_BASE_URL}/api/v1/pools/${poolId}/events`);
    const read = (event: Event, kind: string) => {
      let parsed: unknown;
      try {
        parsed = JSON.parse((event as MessageEvent<string>).data);
      } catch {
        return;
      }
      const frame = record(parsed);
      if (!frame) return;
      if (kind === "tick") {
        const value = text(frame.server_time);
        if (value) setServerNow(value);
      } else if (kind === "pool_status") {
        const value = text(frame.status);
        if (value) setLiveStatus(value);
      } else {
        const lotId = text(frame.lot_id);
        const value = text(frame.status);
        if (lotId && value) setLiveLots((current) => ({ ...current, [lotId]: value }));
      }
    };
    const tick = (event: Event) => read(event, "tick");
    const poolFrame = (event: Event) => read(event, "pool_status");
    const lotFrame = (event: Event) => read(event, "lot_status");
    source.addEventListener("tick", tick);
    source.addEventListener("pool_status", poolFrame);
    source.addEventListener("lot_status", lotFrame);
    return () => {
      source.removeEventListener("tick", tick);
      source.removeEventListener("pool_status", poolFrame);
      source.removeEventListener("lot_status", lotFrame);
      source.close();
    };
  }, [poolId]);

  if (!poolId) {
    return <p className="shop-copy">This pool link is incomplete.</p>;
  }
  if (missing) {
    return (
      <section aria-labelledby="lobby-title">
        <h1 id="lobby-title" className="shop-title">
          Pool not found
        </h1>
        <div className="mt-4">
          <Notice kind="warn">
            This pool has no public page. A draft pool is not open for entries and publishes
            nothing.
          </Notice>
        </div>
        <Link className="shop-quiet-button mt-4" to="/discover">
          <Icon name="arrow" />
          Back to Discover
        </Link>
      </section>
    );
  }
  if (loadError) {
    return (
      <section aria-labelledby="lobby-title">
        <h1 id="lobby-title" className="shop-title">
          Pool lobby
        </h1>
        <div className="mt-4">
          <Notice kind="error" code={loadError.code}>
            {loadError.message}{" "}
            <button
              type="button"
              className="signup-back"
              onClick={() => setAttempt((value) => value + 1)}
            >
              Reload the pool
            </button>
          </Notice>
        </div>
      </section>
    );
  }
  if (!detail || detail.pool_id !== poolId) {
    return (
      <section
        className="shop-panel shop-panel-pad"
        role="status"
        aria-busy="true"
        aria-label="Loading pool"
      >
        <h1 className="shop-title">Pool lobby</h1>
        <div className="skeleton mt-5 h-40" />
      </section>
    );
  }

  const receipt = entryPoolId === poolId && !entryError ? entry?.receipt ?? null : null;
  if (showReceipt && receipt) {
    return (
      <EntryReceiptPage
        receipt={receipt}
        poolTitle={detail.title}
        productDetails={{ condition: detail.condition, variant: detail.variant ?? null, entryStatus: entry?.entry_status ?? "Not available" }}
        onBack={() => setShowReceipt(false)}
      />
    );
  }

  const status = liveStatus ?? detail.status;
  const style = statusStyle(status);
  const timeline = detail.timeline;
  // Both sides of this comparison come from the server (the pool's own close time and the
  // feed's sample), so it is a deadline read, not the device clock deciding eligibility
  // (I15). Before the first tick the screen cannot know, and the server still refuses.
  const windowPassed =
    !!detail.close_at && !!serverNow && Date.parse(serverNow) >= Date.parse(detail.close_at);

  return (
    <section aria-labelledby="lobby-title" className="enter-rise">
      <div className="shop-heading flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <Link className="shop-back" to="/discover">
            <Icon name="arrow" />
            All open pools
          </Link>
          <h1 id="lobby-title" className="font-display text-[32px] leading-[1.12] tracking-[-.04em]">
            {detail.title}
          </h1>
          <p className="shop-copy mt-2">
            {[
              detail.condition,
              detail.variant,
              `${detail.seats} seats`,
              `minimum ${detail.min_seats}`,
            ]
              .filter(Boolean)
              .join(" · ")}
          </p>
        </div>
        <StatusPill status={status} tone={style.tone}>
          {style.label}
        </StatusPill>
      </div>

      {detail.mode === "SIMULATION" ? (
        <div className="mb-5">
          <HonestyLabels kinds={["sandbox", "simulated"]} />
        </div>
      ) : null}

      <div className="pool-page-sections">
        <div className="pool-information">
          <section className="shop-panel lobby-product" aria-label="Product overview">
            <ProductArt title={detail.title} />
            <div>
              <h2>Know what you’re joining</h2>
              <p className="shop-copy">{[detail.condition?.replaceAll("_", " "), detail.variant].filter(Boolean).join(" · ")}. The pool’s published requirements apply to every merchant bid.</p>
              <ul>
                <li>{detail.seats} places across the published lot plan</li>
                <li>Set your maximum before joining</li>
                <li>Approve your own offer at the final price</li>
              </ul>
              <p className="shop-copy text-xs">Category illustration; exact appearance depends on the merchant’s offer.</p>
            </div>
          </section>
          <StageStrip status={status} />
        <section className="pool-entry-section" aria-label="Your place in this pool">
          {entryPoolId !== poolId ? <section className="shop-panel shop-panel-pad" role="status" aria-label="Checking your entry" aria-busy="true"><p>Checking your entry…</p><div className="skeleton mt-4 h-10" /></section>
          : entryError ? <section className="shop-panel shop-panel-pad"><Notice kind="error">We couldn’t check your entry. Try again before joining.</Notice><button type="button" className="button-secondary mt-4" onClick={() => setEntryRevision((value) => value + 1)}>Retry entry check</button></section>
          : <JoinPanel
            detail={detail}
            entry={entry}
            pending={pending}
            status={status}
            windowPassed={windowPassed}
            onCleared={() => setPending(null)}
            onPending={(value) => setPending(value)}
            onViewReceipt={() => setShowReceipt(true)}
            onJoined={() => {
              setPending(null);
              setEntryRevision((value) => value + 1);
              setShowReceipt(false);
            }}
            onWithdrew={() => {
              setShowReceipt(false);
              setEntryRevision((value) => value + 1);
            }}
          />}
          <TrustRow />
        </section>

          <section className="shop-panel" aria-labelledby="lobby-timeline">
            <div className="shop-panel-pad">
              <h2>How this pool runs</h2>
              <p className="shop-copy mt-1">
                One published window. Every entry received before it closes is considered under the
                same rules, and arriving earlier earns no priority.
              </p>
              <dl className="price-rows mt-4">
                <div>
                  <dt>Entry window closes</dt>
                  <dd>
                    {detail.close_at ? (
                      <time dateTime={detail.close_at}>{formatDateTime(detail.close_at)}</time>
                    ) : (
                      "Not published"
                    )}
                  </dd>
                </div>
                <TimelineRow label="Bidding window per lot" seconds={number(timeline.bid_window_s)} />
                <TimelineRow
                  label="Your approval window"
                  seconds={number(timeline.offer_window_s)}
                />
                <TimelineRow
                  label="Funding deadline after approval"
                  seconds={number(timeline.fund_deadline_s)}
                />
                <div>
                  <dt>Delivery zones</dt>
                  <dd>{detail.zone_ids.join(", ") || "Not published"}</dd>
                </div>
              </dl>
            </div>
            <CloseCountdown
              closeAt={detail.close_at ?? null}
              openAt={text(timeline.open_at)}
              serverNow={serverNow}
            />
          </section>

          <LotPlanPanel plan={detail.lot_plan} liveLots={liveLots} />

          <RulesPanel poolId={detail.pool_id} rulesHash={detail.rules_hash ?? null} />
        </div>


      </div>
    </section>
  );
}

/** The four pool stages, with the current one marked from the API's own status. */
function StageStrip({ status }: { status: string }) {
  if (status === "CANCELLED") {
    return (
      <section className="shop-panel shop-panel-pad pool-stage-panel" aria-label="Pool outcome">
        <h2>This pool was cancelled</h2>
        <p className="shop-copy mt-1">
          No lots will be awarded. A pool can only be cancelled while no buyer order exists, so
          nothing was charged and no hold was placed.
        </p>
      </section>
    );
  }
  const current = stageIndex(status);
  return (
    <section className="shop-panel pool-stage-panel" aria-labelledby="lobby-stages">
      <div className="shop-panel-pad">
        <h2 id="lobby-stages">What happens next</h2>
      </div>
      <ol className="order-milestones" aria-label="Pool stages">
        {STAGES.map((stage, index) => (
          <li
            key={stage.label}
            className={index < current ? "milestone-recorded" : ""}
            aria-current={index === current ? "step" : undefined}
          >
            <span className="milestone-dot">
              {index < current ? <Icon name="check" /> : index + 1}
            </span>
            <strong>{stage.label}</strong>
            <small>{index === current ? stage.note : index < current ? "Done" : "Later"}</small>
          </li>
        ))}
      </ol>
    </section>
  );
}

function TrustRow() {
  const notes = [
    { icon: "shield" as const, note: "Auditable under published rules." },
    { icon: "user" as const, note: "One entry per linked PayPal account." },
    { icon: "info" as const, note: "Demonstrated in the PayPal Sandbox." },
  ];
  return (
    <div className="order-disclosures">
      {notes.map((item) => (
        <span key={item.note}>
          <Icon name={item.icon} />
          {item.note}
        </span>
      ))}
    </div>
  );
}

function TimelineRow({ label, seconds }: { label: string; seconds: number | null }) {
  if (seconds === null) return null;
  return (
    <div>
      <dt>{label}</dt>
      <dd>{windowLabel(seconds)}</dd>
    </div>
  );
}

/**
 * The countdown reads the feed&apos;s server sample, never the device clock: until the
 * first `tick` arrives the screen states the deadline in absolute terms rather than
 * showing a time the browser invented (I15).
 */
function CloseCountdown({
  closeAt,
  openAt,
  serverNow,
}: {
  closeAt: string | null;
  openAt: string | null;
  serverNow: string | null;
}) {
  if (!closeAt || !serverNow) {
    return (
      <div className="reservation-note">
        <span>
          <Icon name="clock" />
          Entry window
        </span>
        <time dateTime={closeAt ?? undefined}>
          {closeAt ? formatDateTime(closeAt) : "Not published"}
        </time>
      </div>
    );
  }
  return <LiveCountdown closeAt={closeAt} openAt={openAt} serverNow={serverNow} />;
}

function LiveCountdown({
  closeAt,
  openAt,
  serverNow,
}: {
  closeAt: string;
  openAt: string | null;
  serverNow: string;
}) {
  const countdown = useCountdown(closeAt, serverNow, openAt);
  return (
    <div className={`reservation-note ${countdown.urgent ? "is-urgent" : ""}`}>
      <span>
        <Icon name="clock" />
        {countdown.expired ? "Entry window closed" : "Entry window closes in"}
      </span>
      <time dateTime={closeAt}>{countdown.expired ? "Closed" : countdown.label}</time>
    </div>
  );
}

function LotPlanPanel({
  plan,
  liveLots,
}: {
  plan: PoolDetail["lot_plan"];
  liveLots: Record<string, string>;
}) {
  const reported = Object.entries(liveLots);
  return (
    <section className="shop-panel" aria-labelledby="lobby-lots">
      <div className="shop-panel-pad">
        <h2 id="lobby-lots">Lot plan</h2>
        <p className="shop-copy mt-1">
          A lot is a group of seats in one delivery zone. Each lot is awarded and funded on its
          own, so lots in the same pool can end with different merchants and prices.
        </p>
        {plan.length === 0 ? (
          <p className="shop-copy mt-4">No lots are planned for this pool yet.</p>
        ) : (
          <ul className="item-terms mt-2">
            {plan.map((zone, index) => {
              const zoneId = text(zone.zone_id) ?? `Zone ${index + 1}`;
              const lots = Array.isArray(zone.lots) ? (zone.lots as unknown[]) : [];
              return (
                <li key={`${zoneId}-${index}`}>
                  <Icon name="layers" />
                  <span className="min-w-0">
                    <strong>{zoneId}</strong>{" "}
                    <span className="shop-copy">
                      {lots.length === 0
                        ? "lots not published"
                        : lots
                            .map((lot) => {
                              const row = record(lot) ?? {};
                              const seats = number(row.seats);
                              const minimum = number(row.min_seats);
                              return seats === null
                                ? "a lot"
                                : `${seats} seats${minimum === null ? "" : `, minimum ${minimum}`}`;
                            })
                            .join(" · ")}
                    </span>
                  </span>
                </li>
              );
            })}
          </ul>
        )}
        {reported.length > 0 ? (
          <div className="mt-5">
            <p className="meta-label">Live lot status</p>
            <div className="provider-rows">
              {reported.map(([lotId, value]) => {
                const style = statusStyle(value);
                return (
                  <div key={lotId}>
                    <code className="font-mono text-xs">{lotId}</code>
                    <StatusPill status={value} tone={style.tone}>
                      {style.label}
                    </StatusPill>
                  </div>
                );
              })}
            </div>
          </div>
        ) : null}
      </div>
    </section>
  );
}

function RulesPanel({ poolId, rulesHash }: { poolId: string; rulesHash: string | null }) {
  const [rules, setRules] = useState<ApiComponents["schemas"]["RulesDocument"] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    if (rules !== null || loading) return;
    setLoading(true);
    setError(null);
    try {
      const { data, error: failure } = await api.GET("/api/v1/pools/{pool_id}/rules", {
        params: { path: { pool_id: poolId } },
      });
      if (failure || !data) {
        setError(envelope(failure).message);
        return;
      }
      setRules(data.rules_document);
    } catch {
      setError("Check your connection and try again.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <details
      className="shop-panel shop-disclosure"
      onToggle={(event) => {
        if (event.currentTarget.open) void load();
      }}
    >
      <summary>
        Pool rules and their hash
        <Icon name="down" />
      </summary>
      <p className="signup-help">
        Rules hash: <code className="font-mono break-all">{rulesHash ?? "not published yet"}</code>
      </p>
      {loading ? (
        <p className="shop-copy mt-3" role="status">
          Loading the rules…
        </p>
      ) : null}
      {error ? (
        <p className="shop-copy mt-3">
          {error}{" "}
          <button type="button" className="signup-back" onClick={() => void load()}>
            Try again
          </button>
        </p>
      ) : null}
      {rules !== null ? (
        <div className="published-rules">
          <dl className="published-rule-facts">
            <div><dt>How seats are allocated</dt><dd>{rules.allocation === "seeded_lottery_v1" ? "Seeded lottery" : rules.allocation || "Not published"}</dd></div>
            {typeof rules.require_paypal_link === "boolean" ? <div><dt>PayPal account connection</dt><dd>{rules.require_paypal_link ? "Required to participate" : "Not required by these published rules"}</dd></div> : null}
            {text(rules.template?.title) ? <div><dt>Product</dt><dd>{text(rules.template.title)}</dd></div> : null}
            {Array.isArray(rules.template?.bundle_contents) ? <div><dt>Included items</dt><dd>{rules.template.bundle_contents.filter((item): item is string => typeof item === "string").join(", ")}</dd></div> : null}
            {number(rules.template?.delivery_sla_days) !== null ? <div><dt>Delivery requirement</dt><dd>Within {number(rules.template.delivery_sla_days)} days</dd></div> : null}
            {number(rules.template?.min_return_days) !== null ? <div><dt>Minimum return window</dt><dd>{number(rules.template.min_return_days)} days</dd></div> : null}
            {text(rules.timeline?.open_at) ? <div><dt>Entries open</dt><dd>{formatDateTime(String(rules.timeline.open_at))}</dd></div> : null}
            {text(rules.timeline?.close_at) ? <div><dt>Entries close</dt><dd>{formatDateTime(String(rules.timeline.close_at))}</dd></div> : null}
            {number(rules.refill?.max_refill_waves) !== null ? <div><dt>Maximum refill rounds</dt><dd>{number(rules.refill.max_refill_waves)}</dd></div> : null}
          </dl>
          {Array.isArray(rules.lot_plan) && rules.lot_plan.length > 0 ? <section className="published-lot-plan"><h3>Lots by delivery zone</h3><ul>{rules.lot_plan.map((zone, index) => <li key={index}><strong>{text(zone.zone_id) ?? "Published zone"}</strong><ul>{Array.isArray(zone.lots) ? zone.lots.map((item, row) => {
            const lot = record(item);
            return <li key={row}>Lot {row + 1}: {number(lot?.seats) ?? "Unpublished"} seats; minimum {number(lot?.min_seats) ?? "unpublished"}</li>;
          }) : null}</ul></li>)}</ul></section> : null}
          {rules.disclosures?.lots_may_differ === true ? <p className="shop-copy">Separate lots may have different final prices.</p> : null}
          <p className="shop-copy">The complete published record, selection methods and verification evidence are available on the public audit page below.</p>
        </div>
      ) : null}
      <Link
        className="mt-3 inline-block text-sm font-semibold underline underline-offset-4"
        to={`/audit/${poolId}`}
      >
        Check the pool on the public audit page
      </Link>
    </details>
  );
}

function JoinPanel({
  detail,
  entry,
  pending,
  status,
  windowPassed,
  onCleared,
  onPending,
  onViewReceipt,
  onJoined,
  onWithdrew,
}: {
  detail: PoolDetail;
  entry: EntryStatus | null;
  pending: string | null;
  status: string;
  windowPassed: boolean;
  onCleared: () => void;
  onPending: (value: string) => void;
  onViewReceipt: () => void;
  onJoined: () => void;
  onWithdrew: () => void;
}) {
  const [region, setRegion] = useState(() => deliveryRegions(detail.template)[0] ?? "");
  const [requiredBy, setRequiredBy] = useState("");
  const [maxTotal, setMaxTotal] = useState("");
  const [busy, setBusy] = useState<null | "join" | "withdraw">(null);
  const [confirmWithdraw, setConfirmWithdraw] = useState(false);
  const [problem, setProblem] = useState<{ code: string; message: string } | null>(null);

  const regions = deliveryRegions(detail.template);
  const fundBy = text(detail.template.fund_by);
  // ES-03 admits and withdraws only while the pool is OPEN and before `close_at`; the
  // server is still the one that decides, this only stops the screen offering a dead end.
  const open = status === "OPEN" && !windowPassed;
  const capCents = usdToCents(maxTotal);
  const receipt = entry?.receipt ?? null;

  const join = async (confirmedRequestId: string) => {
    // One key per confirmed request, so a double click or a retry replays the join
    // instead of creating a second entry or a conflict (api.md "Entry").
    const { data, error: failure } = await api.POST("/api/v1/pools/{pool_id}/entries", {
      params: {
        path: { pool_id: detail.pool_id },
        header: { "Idempotency-Key": confirmedRequestId },
      },
      body: { confirmed_request_id: confirmedRequestId },
    });
    if (failure || !data) {
      setProblem(envelope(failure));
      return;
    }
    clearPendingRequest(detail.pool_id);
    onCleared();
    onJoined();
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (busy) return;
    setBusy("join");
    setProblem(null);
    try {
      if (pending) {
        await join(pending);
        return;
      }
      if (!region || !requiredBy || capCents === null) {
        setProblem({
          code: "VALIDATION_ERROR",
          message:
            capCents === null
              ? "Enter your maximum total in dollars, for example 600 or 600.00."
              : "Pick a delivery region and the date you need it by.",
        });
        return;
      }
      const confirmed = await api.POST("/api/v1/intake/manual", {
        body: {
          pool_id: detail.pool_id,
          delivery: { region },
          required_by: requiredBy,
          max_total_cents: capCents,
          firm: [],
          preferences: [],
        },
      });
      if (confirmed.error || !confirmed.data) {
        setProblem(envelope(confirmed.error));
        return;
      }
      // Kept so a failed join below retries against the same request rather than
      // confirming a second one.
      rememberPendingRequest(detail.pool_id, confirmed.data.confirmed_request_id);
      onPending(confirmed.data.confirmed_request_id);
      await join(confirmed.data.confirmed_request_id);
    } catch {
      setProblem({ code: "REQUEST_FAILED", message: "Check your connection and try again." });
    } finally {
      setBusy(null);
    }
  };

  const withdraw = async () => {
    if (busy) return;
    setBusy("withdraw");
    setProblem(null);
    try {
      const { error: failure } = await api.DELETE("/api/v1/pools/{pool_id}/entries/me", {
        params: { path: { pool_id: detail.pool_id } },
      });
      if (failure) {
        setProblem(envelope(failure));
        return;
      }
      setConfirmWithdraw(false);
      onWithdrew();
    } catch {
      setProblem({ code: "REQUEST_FAILED", message: "Check your connection and try again." });
    } finally {
      setBusy(null);
    }
  };

  if (entry) {
    const style = statusStyle(entry.entry_status);
    const withdrawn = entry.entry_status === "WITHDRAWN";
    return (
      <section className="shop-panel" aria-labelledby="lobby-entry">
        <div className="panel-band">
          <h2 id="lobby-entry">Your entry</h2>
          <div className="mt-2 flex items-center justify-between gap-3">
            <p className="shop-copy">{withdrawn ? "No place held." : "Recorded with this pool."}</p>
            <StatusPill status={entry.entry_status} tone={style.tone}>
              {style.label}
            </StatusPill>
          </div>
        </div>
        <div className="shop-panel-pad">
          <p className="font-mono break-all text-xs text-muted">{entry.entry_id}</p>
          {receipt ? (
            <>
              <p className="shop-copy mt-3">
                Your receipt is kept by the pool, not by this browser. It comes back any time you
                open this page.
              </p>
              <button type="button" className="shop-quiet-button mt-4" onClick={onViewReceipt}>
                <Icon name="receipt" />
                View entry receipt
              </button>
            </>
          ) : null}
          {withdrawn ? (
            <p className="shop-copy mt-4">
              Withdrawing gives up your place. The pool keeps the entry on record, and a new entry
              needs a new confirmed request.
            </p>
          ) : entry.entry_status === "SUBMITTED" && open ? (
            <div className="mt-5 rounded-xl bg-accent-tint p-4">
              {confirmWithdraw ? (
                <>
                  <p className="text-sm font-medium">Withdraw your entry from this pool?</p>
                  <p className="shop-copy mt-1">
                    Your place is released and cannot be claimed back later in this window.
                  </p>
                  <div className="address-actions mt-3">
                    <button
                      type="button"
                      className="button-secondary"
                      disabled={busy !== null}
                      onClick={() => void withdraw()}
                    >
                      {busy === "withdraw" ? "Withdrawing…" : "Withdraw entry"}
                    </button>
                    <button
                      type="button"
                      className="signup-back"
                      disabled={busy !== null}
                      onClick={() => setConfirmWithdraw(false)}
                    >
                      Keep my entry
                    </button>
                  </div>
                </>
              ) : (
                <button
                  type="button"
                  className="shop-quiet-button"
                  disabled={busy !== null}
                  onClick={() => setConfirmWithdraw(true)}
                >
                  <Icon name="close" />
                  Withdraw my entry
                </button>
              )}
            </div>
          ) : entry.entry_status === "SUBMITTED" ? (
            <p className="shop-copy mt-4">
              The entry window has closed, so this entry can no longer be withdrawn.
            </p>
          ) : (
            <p className="shop-copy mt-4">
              The pool decides seats after it closes. Your place and your outcome are stated here
              as the server reports them.
            </p>
          )}
          {problem ? (
            <div className="mt-4">
              <Notice kind="error" code={problem.code}>
                {problem.message}
              </Notice>
            </div>
          ) : null}
        </div>
      </section>
    );
  }

  return (
    <section className="shop-panel" aria-labelledby="lobby-join">
      <div className="panel-band">
        <h2 id="lobby-join">{pending ? "Join this pool" : "State your request"}</h2>
        <p className="shop-copy mt-1">{pending ? "One step left." : "Two fields and a cap."}</p>
      </div>
      <div className="shop-panel-pad">
        <p className="flex items-start gap-2 rounded-lg bg-tint px-3 py-2.5 text-xs font-medium leading-relaxed">
          <Icon name="shield" />
          <span>{JOIN_BADGE}</span>
        </p>
        {!open ? (
          <p className="shop-copy">
            {windowPassed && status === "OPEN"
              ? "The entry window has passed its close time, so no new entry can be recorded."
              : `This pool is ${statusStyle(status).label.toLowerCase()}, so no new entry can be recorded.`}
          </p>
        ) : null}
        {problem ? (
          <div className="mb-4">
            <Notice kind="error" code={problem.code}>
              {problem.message}
            </Notice>
          </div>
        ) : null}
        {pending ? (
          <form className="auth-fields mt-1" onSubmit={(event) => void submit(event)}>
            <p className="shop-copy">
              Your request is confirmed and is waiting here for you to record it with this pool.
            </p>
            <button type="submit" className="button-primary w-full" disabled={busy !== null || !open}>
              {busy === "join" ? "Recording…" : "Join this pool"}
              <Icon name="arrow" />
            </button>
          </form>
        ) : (
          <form className="auth-fields mt-1" onSubmit={(event) => void submit(event)}>
            <div className="block">
              <label className="block text-sm font-medium" htmlFor={`region-${detail.pool_id}`}>
                Delivery region
              </label>
              <input
                id={`region-${detail.pool_id}`}
                className="form-input"
                value={region}
                list={`regions-${detail.pool_id}`}
                placeholder={regions.join(", ")}
                onChange={(event) => setRegion(event.target.value)}
                required
              />
              <datalist id={`regions-${detail.pool_id}`}>
                {regions.map((value) => (
                  <option key={value} value={value} />
                ))}
              </datalist>
              {/* The help text sits outside the label so the field's accessible name stays
                  the field's own. */}
              <span className="signup-help">
                {regions.length > 0
                  ? `This pool delivers to ${regions.join(", ")}.`
                  : "This pool has not published a delivery region."}
              </span>
            </div>
            <label className="block">
              <span className="text-sm font-medium">Needed by</span>
              <input
                className="form-input"
                type="date"
                value={requiredBy}
                onChange={(event) => setRequiredBy(event.target.value)}
                required
              />
              {/* Stated, not computed: the date the pool itself publishes. The server owns
                  the rule that a request must leave the merchant time to deliver, and its
                  refusal is what the buyer sees if the date cannot work. */}
              {fundBy !== null ? (
                <span className="signup-help">
                  This pool is funded by {fundBy}, and a merchant must be able to deliver inside
                  that window.
                </span>
              ) : null}
            </label>
            <div className="block">
              <label className="block text-sm font-medium" htmlFor={`cap-${detail.pool_id}`}>
                Your maximum total, in USD
              </label>
              <input
                id={`cap-${detail.pool_id}`}
                className="form-input"
                inputMode="decimal"
                value={maxTotal}
                placeholder="600.00"
                onChange={(event) => setMaxTotal(event.target.value)}
                required
              />
              <span className="signup-help">
                {maxTotal && capCents === null
                  ? "Use digits, with up to two decimals: 600 or 600.00."
                  : capCents !== null
                    ? `Your cap is recorded as ${capCents} cents.`
                    : "The most you would pay for everything, delivered."}
              </span>
            </div>
            <button
              type="submit"
              className="button-primary w-full"
              disabled={busy !== null || !open || (maxTotal !== "" && capCents === null)}
            >
              {busy === "join" ? "Recording…" : "Confirm and join"}
              <Icon name="arrow" />
            </button>
            <p className="signup-help">
              Joining costs nothing and places no hold. If a merchant wins the lot and you are
              given a seat, you get your own offer to approve on PayPal.
            </p>
          </form>
        )}
      </div>
    </section>
  );
}
