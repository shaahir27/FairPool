import { useCallback, useEffect, useState } from "react";

import {
  api,
  type ApiComponents,
  formatDateTime,
  HonestyLabels,
  Notice,
  useCountdown,
} from "../../shared";
import { failureEnvelope, labelsFrom } from "../lib";

import { trackerOf } from "./tracker";

type LotProgress = ApiComponents["schemas"]["LotProgress"];

/**
 * FR-UI-05 tracker: holds against the MOQ until captures begin, then captures.
 * Polling stops while the tab is hidden; every read is the progress endpoint's
 * counts and carries no buyer identity.
 */
export function CheckoutTracker({ lotId, serverNow }: { lotId: string; serverNow: string | null }) {
  const [progress, setProgress] = useState<LotProgress | null>(null);
  const [problem, setProblem] = useState<{ code: string; message: string } | null>(null);

  const load = useCallback(() => {
    if (document.visibilityState === "hidden") return;
    void api
      .GET("/api/v1/merchant/lots/{lot_id}/progress", {
        params: { path: { lot_id: lotId } },
      })
      .then(({ data, error: failure }) => {
        if (data) {
          setProgress(data);
          setProblem(null);
        } else {
          setProblem(failureEnvelope(failure));
        }
      })
      .catch(() =>
        setProblem({
          code: "REQUEST_FAILED",
          message: "Checkout progress could not be loaded.",
        }),
      );
  }, [lotId]);

  useEffect(() => {
    load();
    const id = window.setInterval(load, 5000);
    const onVisibility = () => {
      if (document.visibilityState === "visible") load();
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      window.clearInterval(id);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [load]);

  if (!progress) {
    return problem ? (
      <Notice kind="error" code={problem.code}>
        {problem.message}{" "}
        <button type="button" className="merchant-link" onClick={load}>
          Retry progress
        </button>
      </Notice>
    ) : (
      <p className="shop-copy" role="status">
        Loading checkout progress.
      </p>
    );
  }

  const tracker = trackerOf(progress);
  const kinds = labelsFrom(progress.labels);
  const counts = Object.entries(progress.counts).filter(([, count]) => count > 0);
  // The progress answer carries no payment mode: vault_charge seats are charged,
  // not held, so the pre-capture count stays neutral instead of saying "holds".
  const unit = tracker.phase === "holds" ? "seats held or charged" : "captures completed";

  return (
    <div className="merchant-tracker">
      <p className="merchant-tracker-primary">
        {tracker.primary} of {tracker.target} {unit}
      </p>
      <div
        className="merchant-meter"
        role="progressbar"
        aria-label={`${unit} against the lot minimum`}
        aria-valuemin={0}
        aria-valuemax={tracker.target}
        aria-valuenow={tracker.primary}
      >
        <span style={{ width: `${Math.round(tracker.fraction * 100)}%` }} />
      </div>
      <p className="merchant-help">
        {tracker.phase === "holds"
          ? "Seats held or charged are counted against the minimum until captures begin."
          : "Captures are counted against the minimum."}
        {tracker.remaining > 0
          ? ` ${tracker.remaining} still needed.`
          : tracker.met
            ? " The minimum is met."
            : ""}
      </p>
      <dl className="merchant-facts">
        <div>
          <dt>Seats</dt>
          <dd>{progress.seats}</dd>
        </div>
        <div>
          <dt>Refills offered</dt>
          <dd>{progress.refills_offered}</dd>
        </div>
        <div>
          <dt>Fund by</dt>
          <dd>
            {progress.fund_deadline_at ? (
              <>
                <time dateTime={progress.fund_deadline_at}>
                  {formatDateTime(progress.fund_deadline_at)}
                </time>
                {serverNow ? (
                  <FundCountdown
                    expiresAt={progress.fund_deadline_at}
                    serverNow={serverNow}
                  />
                ) : null}
              </>
            ) : (
              "Not published"
            )}
          </dd>
        </div>
        <div>
          <dt>Lot status</dt>
          <dd>{progress.status}</dd>
        </div>
      </dl>
      {counts.length > 0 ? (
        <>
          <p className="merchant-label">Order status counts</p>
          <ul className="merchant-counts" aria-label="Buyer order status counts">
            {counts.map(([status, count]) => (
              <li key={status}>
                <span>{status}</span>
                <strong>{count}</strong>
              </li>
            ))}
          </ul>
        </>
      ) : null}
      {kinds.length > 0 ? (
        <div className="mt-3">
          <HonestyLabels kinds={kinds} />
        </div>
      ) : null}
    </div>
  );
}

function FundCountdown({ expiresAt, serverNow }: { expiresAt: string; serverNow: string }) {
  const countdown = useCountdown(expiresAt, serverNow);
  return (
    <span className="merchant-countdown">
      {" "}
      · {countdown.expired ? "window closed" : `${countdown.label} left`}
    </span>
  );
}
