import { useEffect, useRef, useState } from "react";

import { api, Notice, StatusPill, statusStyle } from "../shared";

import { failureOf, isLotId, shortId, type AdminLot } from "./api";

type AbortResult = { lot_id: string; status: string; transition_id: string | null };

/** The states the abort route acts on (ops.abort: LS-13, LS-08 and LS-09). */
const ABORTABLE = new Set(["AWARDED", "CHECKOUT_OPEN", "FUNDING"]);

export function LotPanel({ alertLots }: { alertLots: readonly string[] }) {
  const [input, setInput] = useState("");
  const [lot, setLot] = useState<AdminLot | null>(null);
  const [recent, setRecent] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<{ code: string; message: string } | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [aborting, setAborting] = useState(false);
  const [abortResult, setAbortResult] = useState<AbortResult | null>(null);
  // Ties a response to the lookup that asked for it: an older request that
  // resolves late must never replace what the box now names.
  const request = useRef(0);
  const abortTrigger = useRef<HTMLButtonElement>(null);
  const restoreFocus = useRef(false);

  useEffect(() => {
    if (!confirming && restoreFocus.current) {
      restoreFocus.current = false;
      abortTrigger.current?.focus();
    }
  }, [confirming]);

  const closeConfirm = () => {
    restoreFocus.current = true;
    setConfirming(false);
  };

  const lookup = (raw: string) => {
    const lotId = raw.trim();
    setConfirming(false);
    setAbortResult(null);
    if (!isLotId(lotId)) {
      setError({
        code: "VALIDATION_ERROR",
        message: "Enter a lot ID as a UUID, for example 0a1b2c3d-0000-4000-8000-000000000000.",
      });
      return;
    }
    const ticket = ++request.current;
    setLoading(true);
    setError(null);
    void api
      .GET("/api/v1/admin/lots/{lot_id}", { params: { path: { lot_id: lotId } } })
      .then(({ data, error: failure }) => {
        if (ticket !== request.current) return;
        if (failure || !data) {
          setError(failureOf(failure, "The lot could not be loaded."));
          return;
        }
        setLot(data);
        setInput(lotId);
        setRecent((previous) => [lotId, ...previous.filter((item) => item !== lotId)].slice(0, 5));
      })
      .catch(() => {
        if (ticket !== request.current) return;
        setError({ code: "REQUEST_FAILED", message: "The lot could not be loaded. Check your connection and try again." });
      })
      .finally(() => {
        if (ticket === request.current) setLoading(false);
      });
  };

  const abort = () => {
    if (!lot || aborting) return;
    setAborting(true);
    setError(null);
    void api
      .POST("/api/v1/admin/lots/{lot_id}/abort", { params: { path: { lot_id: lot.lot_id } } })
      .then(({ data, error: failure }) => {
        if (failure || !data) {
          setError(failureOf(failure, "The lot could not be aborted."));
          return;
        }
        const result = data as AbortResult;
        setAbortResult(result);
        setLot((current) => (current ? { ...current, status: result.status } : current));
        setConfirming(false);
      })
      .catch(() => {
        setError({ code: "REQUEST_FAILED", message: "The lot could not be aborted. Check your connection and try again." });
      })
      .finally(() => setAborting(false));
  };

  const entries = [...new Set([...recent, ...alertLots])].slice(0, 8);

  return (
    <section className="panel ops-section" aria-labelledby="ops-lot-heading">
      <div className="ops-section-head">
        <div>
          <h2 id="ops-lot-heading">Lot state</h2>
          <p>
            One lot at a time: its state-machine position and the payment router and mode stamped on it.
            Aborting is a two-step, audited action.
          </p>
        </div>
      </div>
      <div className="ops-section-body ops-stack">
        <form
          className="ops-lookup"
          onSubmit={(event) => {
            event.preventDefault();
            // Enter must not queue a second lookup while one is in flight.
            if (loading) return;
            lookup(input);
          }}
        >
          <label className="ops-field">
            Lot ID
            <input
              className="form-input"
              value={input}
              onChange={(event) => {
                setInput(event.target.value);
                // Whatever was loaded belonged to the ID that used to be here.
                request.current += 1;
                setLoading(false);
                setLot(null);
                setConfirming(false);
                setAbortResult(null);
              }}
              placeholder="00000000-0000-4000-8000-000000000000"
              autoComplete="off"
              spellCheck={false}
            />
          </label>
          <button type="submit" className="button-secondary" disabled={loading}>
            {loading ? "Looking up…" : "Look up lot"}
          </button>
        </form>

        {entries.length > 0 ? (
          <div className="ops-recents">
            <p className="ops-label">Recent and alerting lots</p>
            <div className="ops-chip-row">
              {entries.map((entry) => (
                <button
                  key={entry}
                  type="button"
                  className="ops-chip font-mono"
                  title={entry}
                  aria-label={`Look up lot ${entry}`}
                  onClick={() => lookup(entry)}
                >
                  {shortId(entry)}
                </button>
              ))}
            </div>
          </div>
        ) : null}

        {error ? (
          <Notice kind="error" code={error.code}>
            {error.message}
          </Notice>
        ) : null}

        {!lot && !error && !loading ? (
          <p className="ops-empty">
            No lot loaded yet. Enter a lot ID, or pick one that is alerting.
          </p>
        ) : null}

        {lot ? (
          <div className="ops-stack">
            <dl className="ops-facts">
              <div>
                <dt>Lot ID</dt>
                <dd className="font-mono">{lot.lot_id}</dd>
              </div>
              <div>
                <dt>Pool ID</dt>
                <dd className="font-mono">{lot.pool_id}</dd>
              </div>
              <div>
                <dt>Status</dt>
                <dd>
                  <StatusPill status={lot.status} tone={statusStyle(lot.status).tone} />
                </dd>
              </div>
              <div>
                <dt>Seats</dt>
                <dd>
                  {lot.seats} seats, minimum {lot.min_seats}
                </dd>
              </div>
              <div>
                <dt>Award</dt>
                <dd className={lot.award_id ? "font-mono" : undefined}>{lot.award_id ?? "No award yet"}</dd>
              </div>
              <div>
                <dt>Payment router</dt>
                <dd>{lot.payment_router ?? "Not stamped"}</dd>
              </div>
              <div>
                <dt>Payment mode</dt>
                <dd>{lot.payment_mode ?? "Not stamped"}</dd>
              </div>
            </dl>

            <div className="ops-abort">
              {ABORTABLE.has(lot.status) ? (
                confirming ? (
                  <div
                    className="ops-confirm"
                    role="alertdialog"
                    aria-labelledby="ops-abort-title"
                    aria-describedby="ops-abort-copy"
                    onKeyDown={(event) => {
                      if (event.key === "Escape") closeConfirm();
                    }}
                  >
                    <strong id="ops-abort-title">Abort this lot?</strong>
                    <p id="ops-abort-copy">
                      Before checkout the lot is cancelled; during checkout it moves to FAILING so holds are
                      voided and refunded to net zero. This cannot be undone.
                    </p>
                    <div className="ops-confirm-actions">
                      <button
                        type="button"
                        className="button-secondary"
                        disabled={aborting}
                        autoFocus
                        onClick={closeConfirm}
                      >
                        Keep lot running
                      </button>
                      <button
                        type="button"
                        className="button-secondary ops-danger-solid"
                        disabled={aborting}
                        onClick={() => abort()}
                      >
                        {aborting ? "Aborting…" : "Yes, abort lot"}
                      </button>
                    </div>
                  </div>
                ) : (
                  <button
                    ref={abortTrigger}
                    type="button"
                    className="button-secondary ops-danger"
                    aria-label={`Abort lot ${lot.lot_id}`}
                    onClick={() => setConfirming(true)}
                  >
                    Abort lot
                  </button>
                )
              ) : (
                <p className="ops-note">
                  Abort applies to AWARDED, CHECKOUT_OPEN and FUNDING lots. This lot is {lot.status}.
                </p>
              )}
            </div>

            {abortResult ? (
              <Notice kind="info">
                {abortResult.transition_id
                  ? `Lot moved to ${abortResult.status} (${abortResult.transition_id}).`
                  : `Nothing changed: the lot was already ${abortResult.status}.`}
              </Notice>
            ) : null}
          </div>
        ) : null}
      </div>
    </section>
  );
}
