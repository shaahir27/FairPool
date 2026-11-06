import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";

import {
  api,
  envelope,
  formatCents,
  HonestyLabels,
  Notice,
  PublicLayout,
  StatusPill,
  useApiRead,
  type ApiComponents,
} from "../shared";
import {
  checkPlace,
  commitment as commitmentOf,
  merkleRoot,
  rulesHash,
  verifyEd25519,
  withoutSignature,
} from "./verify";

type Audit = ApiComponents["schemas"]["PublicAuditResponse"];
type AuditLot = ApiComponents["schemas"]["AuditLot"];

/** One recomputation the visitor is shown as a verdict, never as a claim. */
type Verdict = {label: string; detail: string; ok: boolean | null};

const PENDING: Verdict[] = [
  {label: "Rules hash", detail: "Recomputing the published rules document…", ok: null},
  {label: "Entries root", detail: "Rebuilding the Merkle root from the published list…", ok: null},
  {label: "Chain checkpoint", detail: "Verifying the checkpoint signature…", ok: null},
];

async function verdicts(audit: Audit, publicKey: string | null): Promise<Verdict[]> {
  const list = audit.commitments ?? [];
  const recomputedRules = await rulesHash(audit.rules_document);
  const recomputedRoot = await merkleRoot(list);
  const proof = audit.checkpoint;
  const signatureOk =
    proof === null || proof === undefined || publicKey === null
      ? null
      : await verifyEd25519(withoutSignature(proof as unknown as Record<string, unknown>), String(proof.signature), publicKey);
  return [
    {
      label: "Rules hash",
      detail:
        recomputedRules === audit.rules_hash
          ? "The published rules document hashes to the served rules_hash."
          : `Served ${short(audit.rules_hash)}, recomputed ${short(recomputedRules)}.`,
      ok: recomputedRules === audit.rules_hash,
    },
    {
      label: "Entries root",
      detail:
        audit.entries_root === null
          ? "Nothing to check yet: the commitment list is published at the close."
          : recomputedRoot === audit.entries_root
            ? `${list.length} commitments rebuilt to the published root.`
            : `Published ${short(audit.entries_root)}, recomputed ${short(recomputedRoot)}.`,
      ok: audit.entries_root === null ? null : recomputedRoot === audit.entries_root,
    },
    {
      label: "Chain checkpoint",
      detail:
        proof === null || proof === undefined
          ? "No checkpoint published yet. It appears once bidding has closed (CR-11)."
          : signatureOk
            ? `Row ${proof.head_seq} verified against the published key.`
            : "The signature does not verify against the published key.",
      ok: signatureOk,
    },
  ];
}

function short(value: string | null | undefined): string {
  return value === null || value === undefined ? "none" : `${value.slice(0, 12)}…`;
}

function lotFor(lots: AuditLot[], rank: number): AuditLot | undefined {
  return lots.find((lot) => lot.rank_range.length === 2 && rank >= lot.rank_range[0]! && rank <= lot.rank_range[1]!);
}

export function AuditPage() {
  const {poolId} = useParams<{poolId: string}>();
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
    void verdicts(audit, publicKey).then((rows) => {
      if (live) setChecks(rows);
    });
    return () => {
      live = false;
    };
  }, [audit, publicKey]);

  const [entryId, setEntryId] = useState("");
  const [requestHash, setRequestHash] = useState("");
  const [saltHex, setSaltHex] = useState("");
  const [place, setPlace] = useState<string>("");

  const lotRows = useMemo(() => audit?.lots ?? [], [audit]);

  async function verifyPlace(event: React.FormEvent) {
    event.preventDefault();
    // The seed is optional AND nullable in the served schema, so both are checked
    // before it reaches a hash function.
    const seed = audit?.seed_hex;
    if (audit === null || seed === null || seed === undefined || poolId === undefined) {
      setPlace("The seed is published after the close and after bidding has ended.");
      return;
    }
    try {
      const target = await commitmentOf(poolId, entryId.trim(), requestHash.trim(), saltHex.trim());
      const result = await checkPlace(seed, audit.commitments ?? [], target);
      if (!result.found) {
        setPlace(`Your commitment ${short(target)} is not in the published list of ${(audit.commitments ?? []).length}.`);
        return;
      }
      const lot = lotFor(lotRows, result.rank);
      setPlace(
        `Your commitment recomputes to ${short(target)}, listed at position ${result.index + 1} of the sorted list. ` +
          `With the published seed your rank is ${result.rank}` +
          (lot ? `, which falls inside lot ${lot.lot_order + 1} (ranks ${lot.rank_range[0]}–${lot.rank_range[1]}, ${lot.zone_id}).` : ", which falls outside every filled lot — you are on the waitlist."),
      );
    } catch (problem) {
      setPlace(`Cannot recompute: ${problem instanceof Error ? problem.message : "check the three receipt fields."}`);
    }
  }

  if (read.error) {
    const problem = envelope(read.error);
    return (
      <PublicLayout perspective="Public audit">
        <Notice kind="error" code={problem.code}>
          This pool's audit record could not be read. {problem.message}
        </Notice>
      </PublicLayout>
    );
  }

  if (audit === null) {
    return (
      <PublicLayout perspective="Public audit">
        <p role="status" aria-label="Loading audit record">
          Loading the published audit record…
        </p>
      </PublicLayout>
    );
  }

  return (
    <PublicLayout perspective="Public audit">
      <div className="shop-heading">
        <h1 className="shop-title">Public audit</h1>
        <p className="shop-copy">
          Everything below is what FairPool published. Each check is recomputed in this browser from the
          values on the page, so a match is your own arithmetic, not our assertion.
        </p>
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        <StatusPill status={audit.pool_status}>Pool {audit.pool_status}</StatusPill>
        {audit.seed_is_demo ? <HonestyLabels kinds={["demoSeed"]} /> : null}
        {audit.seed_hex === null ? <span className="shop-copy">Seed not published yet</span> : null}
      </div>

      <ul className="mt-4">
        {checks.map((verdict) => (
          <li key={verdict.label} className="shop-panel shop-panel-pad">
            <strong>{verdict.label}</strong>
            <p className="shop-copy">{verdict.detail}</p>
            {verdict.ok === true ? <span aria-label="Check passed">✓ matches</span> : null}
            {verdict.ok === false ? <span aria-label="Check failed">✗ does not match</span> : null}
          </li>
        ))}
      </ul>

      <dl className="mt-4">
        <dt>Rules hash</dt>
        <dd>{audit.rules_hash}</dd>
        <dt>Entries root</dt>
        <dd>{audit.entries_root ?? "published at close"}</dd>
        <dt>Commitments published</dt>
        <dd>{audit.entries_count ?? 0}</dd>
        <dt>Seed</dt>
        <dd>{audit.seed_hex ?? "not yet revealed"}</dd>
        <dt>Beacon</dt>
        <dd>{audit.beacon === null || audit.beacon === undefined ? "not yet revealed" : JSON.stringify(audit.beacon)}</dd>
      </dl>

      {lotRows.length > 0 ? (
        <table className="mt-4">
          <caption>Lot boundaries and the bid-set commitments</caption>
          <thead>
            <tr>
              <th scope="col">Lot</th>
              <th scope="col">Zone</th>
              <th scope="col">Seats</th>
              <th scope="col">Ranks</th>
              <th scope="col">Bid set root</th>
              <th scope="col">Bids</th>
              <th scope="col">Delivered price</th>
            </tr>
          </thead>
          <tbody>
            {lotRows.map((lot) => (
              <tr key={String(lot.lot_id)}>
                <th scope="row">{lot.lot_order + 1}</th>
                <td>{lot.zone_id}</td>
                <td>{lot.seats}</td>
                <td>{lot.rank_range.length === 2 ? `${lot.rank_range[0]}–${lot.rank_range[1]}` : "—"}</td>
                <td>{lot.bids_root === null || lot.bids_root === undefined ? "not recorded" : short(lot.bids_root)}</td>
                <td>{lot.bids_count ?? "—"}</td>
                <td>{lot.award ? formatCents(lot.award.item_cents) : "no award"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}

      <form className="mt-4" onSubmit={(event) => void verifyPlace(event)}>
        <h2>Verify my place</h2>
        <p className="shop-copy">
          Paste the three values from your entry receipt. Nothing is sent anywhere: the commitment, its
          position in the published list and your rank are computed here.
        </p>
        <label>
          Entry id
          <input value={entryId} onChange={(event) => setEntryId(event.target.value)} autoComplete="off" />
        </label>
        <label>
          Request hash
          <input value={requestHash} onChange={(event) => setRequestHash(event.target.value)} autoComplete="off" />
        </label>
        <label>
          Salt
          <input value={saltHex} onChange={(event) => setSaltHex(event.target.value)} autoComplete="off" />
        </label>
        <button type="submit" disabled={entryId === "" || requestHash === "" || saltHex === ""}>
          Recompute my place
        </button>
        {/* Notice also carries role="status", so this live region needs its own name. */}
        <p role="status" aria-live="polite" aria-label="Recomputed place">
          {place}
        </p>
      </form>

      <Notice kind="info">
        What this page cannot prove: that the commitment list is complete, that a commitment matches the
        request behind it (the salts stay with each buyer), or that the beacon round's BLS signature is
        valid; FairPool does not verify that signature, and an outside auditor holding the drand public key can.
        Selection is auditable under published rules; it is not provably fair. A rank tie would be broken
        by entry id, which the published list does not carry.
      </Notice>
    </PublicLayout>
  );
}
