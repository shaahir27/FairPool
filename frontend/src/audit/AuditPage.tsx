import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";

import {
  accountState,
  api,
  envelope,
  formatCents,
  HonestyLabels,
  Icon,
  Notice,
  PublicLayout,
  resetSessionCache,
  sessionState,
  setAccount,
  useApiRead,
  type Account,
  type ApiComponents,
} from "../shared";
import { BuyerLayout } from "../buyer";
import {
  checkPlace,
  commitment as commitmentOf,
  merkleRoot,
  rulesHash,
  verifyEd25519,
  withoutSignature,
} from "./verify";
import "./audit.css";

type Audit = ApiComponents["schemas"]["PublicAuditResponse"];
type AuditLot = ApiComponents["schemas"]["AuditLot"];
type Checkpoint = NonNullable<Audit["checkpoint"]>;

/** One recomputation the visitor is shown as a verdict, never as a claim. */
type Verdict = {
  label: string;
  detail: string;
  ok: boolean | null;
  facts: {term: string; value: string}[];
  list?: string[];
};

const PENDING: Verdict[] = [
  {label: "Published rules", detail: "Recalculating the rules document…", ok: null, facts: []},
  {label: "Entry list", detail: "Rebuilding the entry fingerprint…", ok: null, facts: []},
  {label: "Tamper seal", detail: "Verifying the seal…", ok: null, facts: []},
];

async function verdicts(audit: Audit, publicKey: string | null): Promise<Verdict[]> {
  const list = audit.commitments ?? [];
  const recomputedRules = await rulesHash(audit.rules_document);
  const recomputedRoot = await merkleRoot(list);
  const proof: Checkpoint | null = audit.checkpoint ?? null;
  const signatureOk =
    proof === null || publicKey === null
      ? null
      : await verifyEd25519(
          withoutSignature(proof as unknown as Record<string, unknown>),
          String(proof.signature),
          publicKey,
        );
  const rulesOk = recomputedRules === audit.rules_hash;
  return [
    {
      label: "Published rules",
      detail: rulesOk
        ? "The rules served with this page are the ones FairPool froze when the pool was published."
        : `Served ${short(audit.rules_hash)}, recomputed ${short(recomputedRules)}. The document here is not the one that was frozen.`,
      ok: rulesOk,
      facts: [
        {term: "Published hash", value: audit.rules_hash},
        {term: "Recomputed here", value: recomputedRules},
      ],
    },
    {
      label: "Entry list",
      detail:
        audit.entries_root === null
          ? "Nothing to check yet: the entry list is published when entries close."
          : recomputedRoot === audit.entries_root
            ? `${list.length} entries rebuild the published fingerprint.`
            : `Published ${short(audit.entries_root)}, recomputed ${short(recomputedRoot)}.`,
      ok: audit.entries_root === null ? null : recomputedRoot === audit.entries_root,
      facts: [
        {term: "Published fingerprint", value: audit.entries_root ?? "not published yet"},
        {term: "Recomputed here", value: recomputedRoot},
        {term: "Entries in the list", value: String(list.length)},
      ],
      list,
    },
    {
      label: "Tamper seal",
      detail:
        proof === null
          ? "No signed checkpoint has been published yet."
          : publicKey === null
            ? "The seal could not be checked here: FairPool's public key has not loaded."
            : signatureOk
              ? `Seal number ${proof.head_seq} verifies with FairPool's published key.`
              : "The seal does not verify with the published key.",
      ok: signatureOk,
      facts:
        proof === null
          ? [{term: "Seal", value: "not published yet"}]
          : [
              {term: "Seal number", value: String(proof.head_seq)},
              {term: "Last action hash", value: String(proof.head_hash ?? "not published")},
              {term: "Signature", value: String(proof.signature)},
              {term: "FairPool's public key", value: publicKey ?? "not loaded"},
            ],
    },
  ];
}

function short(value: string | null | undefined): string {
  return value === null || value === undefined ? "none" : `${value.slice(0, 12)}…`;
}

/**
 * The page keeps the buyer's own navigation when a buyer is signed in, and falls
 * back to the public shell for everyone else: an audit link is shareable, but a
 * buyer arriving from their pool must not lose the sidebar on the way.
 */
function useSessionAccount(): Account | null {
  const [account, setLocal] = useState<Account | null>(accountState());
  useEffect(() => {
    if (account !== null || sessionState() === "out") return;
    let live = true;
    // Same answer RequireAuth would ask for; a refused call proves nothing.
    void api
      .GET("/api/v1/me")
      .then(({data, response}) => {
        if (!live) return;
        if (response.status === 401) {
          resetSessionCache("out");
          return;
        }
        if (!response.ok || typeof data?.role !== "string") return;
        resetSessionCache("in");
        const next = {
          display_name: typeof data.display_name === "string" ? data.display_name : "",
          role: data.role,
          paypal_linked: data.paypal_linked === true,
        };
        setAccount(next);
        setLocal(next);
      })
      .catch(() => {});
    return () => {
      live = false;
    };
  }, [account]);
  return account;
}

function Shell({ children, account }: { children: ReactNode; account: Account | null }) {
  if (account?.role === "buyer") {
    return <BuyerLayout>{children}</BuyerLayout>;
  }
  return <PublicLayout perspective="Public audit">{children}</PublicLayout>;
}

function lotFor(lots: AuditLot[], rank: number): AuditLot | undefined {
  return lots.find((lot) => lot.rank_range.length === 2 && rank >= lot.rank_range[0]! && rank <= lot.rank_range[1]!);
}

/** The title and zone names are inside the frozen rules document, so no extra call. */
function rulesShape(document: Record<string, unknown>): {
  title: string | null;
  zones: Map<string, string>;
} {
  const template = document.template;
  if (template === null || typeof template !== "object") return {title: null, zones: new Map()};
  const record = template as Record<string, unknown>;
  const title = typeof record.title === "string" ? record.title : null;
  const zones = new Map<string, string>();
  if (Array.isArray(record.zones)) {
    for (const zone of record.zones) {
      if (zone === null || typeof zone !== "object") continue;
      const entry = zone as Record<string, unknown>;
      if (typeof entry.zone_id === "string") {
        zones.set(entry.zone_id, typeof entry.label === "string" ? entry.label : entry.zone_id);
      }
    }
  }
  return {title, zones};
}

export function AuditPage() {
  const {poolId} = useParams<{poolId: string}>();
  const account = useSessionAccount();
  const read = useApiRead(`/api/v1/public/pools/${poolId}/audit`, (signal) =>
    api.GET("/api/v1/public/pools/{pool_id}/audit", {signal, params: {path: {pool_id: poolId!}}}),
  );
  const keys = useApiRead("/api/v1/public/keys", (signal) => api.GET("/api/v1/public/keys", {signal}));
  const audit = read.data ?? null;
  const publicKey = keys.data?.public_key ?? null;

  const [checks, setChecks] = useState<Verdict[]>(PENDING);
  useEffect(() => {
    let live = true;
    if (audit === null) {
      setChecks(PENDING);
      return;
    }
    void verdicts(audit, publicKey)
      .then((rows) => {
        if (live) setChecks(rows);
      })
      .catch(() => {
        // A page that cannot recompute must say so instead of staying on "Recalculating…".
        if (live) {
          setChecks([
            {label: "Published rules", detail: "These checks could not run in this browser.", ok: null, facts: []},
            {label: "Entry list", detail: "These checks could not run in this browser.", ok: null, facts: []},
            {label: "Tamper seal", detail: "These checks could not run in this browser.", ok: null, facts: []},
          ]);
        }
      });
    return () => {
      live = false;
    };
  }, [audit, publicKey]);

  useEffect(() => {
    setPlace("");
    setEntryId(""); setRequestHash(""); setSaltHex(""); setReceiptPoolId(null);
  }, [poolId]);

  const [entryId, setEntryId] = useState("");
  const [requestHash, setRequestHash] = useState("");
  const [saltHex, setSaltHex] = useState("");
  const [place, setPlace] = useState<string>("");
  const [receiptPoolId, setReceiptPoolId] = useState<string | null>(null);
  const receiptRequested = poolId !== undefined && receiptPoolId === poolId;
  const ownEntry = useApiRead(`/api/v1/pools/${poolId}/entries/me`, (signal) =>
    api.GET("/api/v1/pools/{pool_id}/entries/me", {signal, params: {path: {pool_id: poolId!}}}),
    {enabled: receiptRequested && account?.role === "buyer" && Boolean(poolId)},
  );
  useEffect(() => {
    const receipt = ownEntry.data?.receipt;
    if (!receiptRequested || !receipt || receipt.payload.pool_id !== poolId) return;
    setEntryId(receipt.payload.entry_id);
    setRequestHash(receipt.request_hash);
    setSaltHex(receipt.salt_hex);
    setPlace("");
  }, [ownEntry.data, poolId, receiptRequested]);

  const lotRows = useMemo(() => audit?.lots ?? [], [audit]);
  const shape = useMemo(
    () => rulesShape((audit?.rules_document ?? {}) as Record<string, unknown>),
    [audit],
  );
  const areaOf = (zoneId: string) => shape.zones.get(zoneId) ?? zoneId;

  async function verifyPlace(event: React.FormEvent) {
    event.preventDefault();
    // The seed is optional AND nullable in the served schema, so both are checked
    // before it reaches a hash function.
    const seed = audit?.seed_hex;
    if (audit === null || seed === null || seed === undefined || poolId === undefined) {
      setPlace("Your rank can be checked when the seed is public, after entry and bidding windows have closed.");
      return;
    }
    try {
      const target = await commitmentOf(poolId, entryId.trim(), requestHash.trim(), saltHex.trim());
      const list = audit.commitments ?? [];
      const result = await checkPlace(seed, list, target);
      if (!result.found) {
        setPlace(`Your entry is not in the published list of ${list.length}.`);
        return;
      }
      const lot = lotFor(lotRows, result.rank);
      setPlace(
        `Your entry is listed at position ${result.index + 1} of ${list.length}. ` +
          `With the published seed your rank is ${result.rank}` +
          (lot
            ? `, which falls inside lot ${lot.lot_order} (ranks ${lot.rank_range[0]}–${lot.rank_range[1]}, ${areaOf(lot.zone_id)}).`
            : ", which is outside every filled lot — you are on the waitlist."),
      );
    } catch (problem) {
      setPlace(`Cannot recompute: ${problem instanceof Error ? problem.message : "check the three receipt fields."}`);
    }
  }

  if (read.error) {
    const problem = envelope(read.error);
    return (
      <Shell account={account}>
        <Link className="shop-back" to={`/pools/${poolId}`}>
          <Icon name="arrow" />
          Back to the pool
        </Link>
        <header className="audit-head"><h1 className="audit-title">Public audit</h1><p className="audit-lede">The published record is unavailable. You can retry without leaving this page.</p></header>
        <Notice kind="error" code={problem.code}>
          This pool's audit record could not be read. {problem.message}
          <button type="button" className="button-secondary" onClick={() => void read.refetch()}>Retry audit</button>
        </Notice>
      </Shell>
    );
  }

  if (audit === null) {
    return (
      <Shell account={account}>
        <Link className="shop-back" to={`/pools/${poolId}`}>
          <Icon name="arrow" />
          Back to the pool
        </Link>
        <div className="audit">
          <header className="audit-head">
            <h1 className="audit-title">Public audit</h1>
            <p className="audit-lede">
              Reading the published record. Every check is recalculated in your browser
              once it arrives.
            </p>
          </header>
          <div className="audit-panel audit-skeleton" role="status" aria-label="Loading audit record">
            <span className="sr-only">Loading the published audit record…</span>
            <span className="audit-skeleton-row" />
            <span className="audit-skeleton-row" />
            <span className="audit-skeleton-row" />
          </div>
        </div>
      </Shell>
    );
  }

  const beacon = audit.beacon as Record<string, unknown> | null;
  const beaconRound = beacon && typeof beacon.round === "number" ? beacon.round : null;
  const seedLine =
    audit.seed_is_demo
      ? "Seed chosen by FairPool for this demo — not a public draw."
      : audit.seed_hex === null || audit.seed_hex === undefined
        ? "Seed not yet public. It stays private while lots can still receive bids."
        : beaconRound === null
          ? "Seed taken from the announced public beacon round."
          : `Seed from public beacon round ${beaconRound}.`;

  return (
    <Shell account={account}>
      <Link className="shop-back" to={`/pools/${poolId}`}>
        <Icon name="arrow" />
        Back to the pool
      </Link>
      <div className="audit">
        <header className="audit-head">
          <h1 className="audit-title">Public audit</h1>
          <p className="audit-pool">
            {shape.title ?? "This pool"} <span>· Sandbox</span>
          </p>
          <p className="audit-lede">
            Compare the published rules, entry list and tamper seal. These checks
            are recalculated in your browser from the published record.
          </p>
          <div className="audit-meta">
            <span>
              Pool status <code>{audit.pool_status}</code>
            </span>
            <span>{seedLine}</span>
            {audit.seed_is_demo ? <HonestyLabels kinds={["demoSeed"]} /> : null}
          </div>
        </header>

        <nav className="audit-navigation" aria-label="Audit sections">
          <a href="#audit-checks-title">Overview</a>
          <a href="#audit-place-title">Check your place</a>
          {lotRows.length > 0 ? <a href="#audit-draw-title">Draw and lots</a> : null}
          <a href="#audit-limits-title">Limits</a>
          <a href="#audit-evidence">Published evidence</a>
        </nav>
        <div className="audit-workbench">
        <section className="audit-section audit-tool" aria-labelledby="audit-place-title">
          <h2 id="audit-place-title">Check your own place</h2>
          <p>
            Check that your entry appears in the published list and recompute its rank.
            The calculation runs in this tab; your receipt values are not submitted.
          </p>
          {account?.role === "buyer" ? <>
            <button type="button" className="button-primary" disabled={ownEntry.isFetching} onClick={() => { if (receiptRequested) void ownEntry.refetch(); else setReceiptPoolId(poolId ?? null); }}>
              {ownEntry.isFetching ? "Loading your receipt…" : "Use my saved receipt"}
            </button>
            {ownEntry.error || (receiptRequested && ownEntry.data && !ownEntry.data.receipt) ? <Notice kind="warn">We couldn’t load a saved receipt for this pool. Try again or enter your receipt below.</Notice> : null}
          </> : null}
          <details className="audit-more audit-manual" open={account?.role !== "buyer" || receiptRequested}>
            <summary>{receiptRequested && ownEntry.data?.receipt ? "Review your receipt values" : "Enter receipt values manually"}</summary>
          <form className="audit-form" onSubmit={(event) => void verifyPlace(event)}>
            <div className="audit-fields">
              <label htmlFor="audit-entry-id">
                Entry id
                <input
                  id="audit-entry-id"
                  className="form-input"
                  value={entryId}
                  onChange={(event) => setEntryId(event.target.value)}
                  autoComplete="off"
                  spellCheck={false}
                  autoCapitalize="none"
                  aria-describedby="audit-receipt-help"
                />
              </label>
              <label htmlFor="audit-request-hash">
                Request hash
                <input
                  id="audit-request-hash"
                  className="form-input"
                  value={requestHash}
                  onChange={(event) => setRequestHash(event.target.value)}
                  autoComplete="off"
                  spellCheck={false}
                  autoCapitalize="none"
                  aria-describedby="audit-receipt-help"
                />
              </label>
              <label htmlFor="audit-salt">
                Salt
                <input
                  id="audit-salt"
                  className="form-input"
                  value={saltHex}
                  onChange={(event) => setSaltHex(event.target.value)}
                  autoComplete="off"
                  spellCheck={false}
                  autoCapitalize="none"
                  aria-describedby="audit-receipt-help"
                />
              </label>
            </div>
            <p className="audit-help" id="audit-receipt-help">
              The receipt is the page shown when your entry was accepted; the salt is the
              long random string in it, revealed only to you.
            </p>
            <button
              type="submit"
              className="button-primary"
              disabled={entryId === "" || requestHash === "" || saltHex === ""}
            >
              Recompute my place
            </button>
            {/* A live region with its own name: the result is announced once, here. */}
            <p role="status" aria-live="polite" data-testid="audit-place" className="audit-result">
              {place}
            </p>
          </form>
          </details>
        </section>
        <section className="audit-section audit-summary" aria-labelledby="audit-checks-title">
          <h2 id="audit-checks-title">The three checks</h2>
          <div>
            <div className="audit-checks">
              {checks.map((verdict) => (
                <article key={verdict.label} className="audit-check">
                  <span
                    className={`audit-mark ${verdict.ok === true ? "is-ok" : verdict.ok === false ? "is-bad" : "is-wait"}`}
                    aria-label={verdict.ok === true ? "Check passed" : verdict.ok === false ? "Check failed" : undefined}
                    aria-hidden={verdict.ok === null ? true : undefined}
                  >
                    <Icon name={verdict.ok === true ? "check" : verdict.ok === false ? "close" : "info"} />
                  </span>
                  <div>
                    <div className="audit-check-heading"><h3>{verdict.label}</h3><span className="audit-check-state">{verdict.ok === true ? "Match" : verdict.ok === false ? "Mismatch" : "Not checked"}</span></div>
                    <p>{verdict.detail}</p>
                    {verdict.ok === null ? null : (
                      <details className="audit-more">
                        <summary>Show the exact values</summary>
                        <dl className="audit-values">
                          {verdict.facts.map((fact) => (
                            <div key={fact.term}>
                              <dt>{fact.term}</dt>
                              <dd>{fact.value}</dd>
                            </div>
                          ))}
                        </dl>
                        {verdict.list !== undefined && verdict.list.length > 0 ? (
                          <>
                            <p className="audit-list-label">Published commitments, in order</p>
                            <ol className="audit-list" tabIndex={0} aria-label="Published commitments">
                              {verdict.list.map((item) => (
                                <li key={item}>{item}</li>
                              ))}
                            </ol>
                          </>
                        ) : null}
                      </details>
                    )}
                  </div>
                </article>
              ))}
            </div>
          </div>
        </section>


        </div>

        {lotRows.length > 0 ? (
          <section className="audit-section" aria-labelledby="audit-draw-title">
            <h2 id="audit-draw-title">The draw</h2>
            <p>
              Entries were ordered by the published seed and cut into lots in rank order.
              Each winning bid is shown as recorded. Your individual offer shows the full total you would approve.
            </p>
            <div className="audit-panel audit-table-wrap">
              <table className="audit-table" role="table">
                <caption className="audit-caption">
                  Lots, the ranks each one took, and what it won at.
                </caption>
                <thead>
                  <tr>
                    <th scope="col">Lot</th>
                    <th scope="col">Area</th>
                    <th scope="col">Seats</th>
                    <th scope="col">Ranks</th>
                    <th scope="col">Bids</th>
                    <th scope="col">Winning bid</th>
                    <th scope="col">Bid seal</th>
                  </tr>
                </thead>
                <tbody>
                  {lotRows.map((lot) => (
                    <tr key={String(lot.lot_id)}>
                      <th scope="row" data-label="Lot">{lot.lot_order}</th>
                      <td data-label="Area">{areaOf(lot.zone_id)}</td>
                      <td className="audit-num" data-label="Seats">{lot.seats}</td>
                      <td className="audit-num" data-label="Ranks">
                        {lot.rank_range.length === 2 ? `${lot.rank_range[0]}–${lot.rank_range[1]}` : "—"}
                      </td>
                      <td className="audit-num" data-label="Bids">{lot.bids_count ?? "—"}</td>
                      <td className="audit-num audit-price" data-label="Winning bid">
                        {lot.award ? formatCents(lot.award.item_cents) : "No award"}
                      </td>
                      <td data-label="Bid seal">
                        {lot.bids_root === null || lot.bids_root === undefined ? (
                          <span className="audit-seal">
                            {lot.status === "PLANNED" || lot.status === "BIDDING"
                              ? "sealed at bid close"
                              : "not recorded"}
                          </span>
                        ) : (
                          <span className="audit-seal" title={lot.bids_root}>
                            {short(lot.bids_root)}
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        ) : null}

        <section className="audit-section" aria-labelledby="audit-limits-title">
          <h2 id="audit-limits-title">What this page cannot prove</h2>
          <ul className="audit-limits">
            <li>
              <strong>Completeness.</strong> Every commitment FairPool published is here, but
              the page cannot show that no entry was left out.
            </li>
            <li>
              <strong>Ownership.</strong> A commitment hides the request behind it; the salt
              stays with each buyer. Recomputing your own proves your entry, not anyone else's.
            </li>
            <li>
              <strong>The beacon.</strong> FairPool reads the round's published value but does
              not verify that signature; an outside auditor holding the drand public key can.
              Selection is auditable under published rules; it is not provably fair. A rank
              tie would be broken by entry id, which the published list does not carry.
            </li>
          </ul>
        </section>

        <details id="audit-evidence" className="audit-section audit-more audit-raw">
          <summary>Published values, for auditors</summary>
          <dl className="audit-values" aria-label="Published evidence">
            <div>
              <dt>Rules hash</dt>
              <dd>{audit.rules_hash}</dd>
            </div>
            <div>
              <dt>Entry fingerprint</dt>
              <dd>{audit.entries_root ?? "published at close"}</dd>
            </div>
            <div>
              <dt>Entries published</dt>
              <dd>{audit.entries_count ?? "not yet published"}</dd>
            </div>
            <div>
              <dt>Seed</dt>
              <dd>{audit.seed_hex ?? "not yet revealed"}</dd>
            </div>
            <div>
              <dt>Beacon</dt>
              <dd>
                {audit.beacon === null || audit.beacon === undefined
                  ? "not yet revealed"
                  : JSON.stringify(audit.beacon)}
              </dd>
            </div>
          </dl>
        </details>
      </div>
    </Shell>
  );
}
