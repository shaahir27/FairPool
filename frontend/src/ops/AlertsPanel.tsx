import { formatDateTime, Notice, StatusPill, type StatusTone } from "../shared";

import { shortId, type AlertRow } from "./api";

const SEVERITY: Readonly<Record<string, { label: string; tone: StatusTone }>> = {
  webhook_dead_letter: { label: "Act now", tone: "bad" },
  lot_past_fund_deadline: { label: "Act now", tone: "bad" },
  lot_failing: { label: "Act now", tone: "bad" },
  authorization_aged: { label: "Watch", tone: "active" },
};

const KIND_LABELS: Readonly<Record<string, string>> = {
  webhook_dead_letter: "Webhook dead letter",
  lot_past_fund_deadline: "Lot past its fund deadline",
  authorization_aged: "Authorization older than the guard",
  lot_failing: "Lot failing beyond one sweep",
};

function formatAge(seconds: number | undefined): string | null {
  if (typeof seconds !== "number" || !Number.isFinite(seconds)) return null;
  if (seconds < 3600) return `${Math.max(1, Math.round(seconds / 60))} min`;
  if (seconds < 86_400) return `${Math.round(seconds / 3600)} h`;
  return `${Math.round(seconds / 86_400)} d`;
}

function alertWhen(alert: AlertRow): string {
  const iso = alert.received_at ?? alert.fund_deadline_at ?? alert.failing_since;
  if (iso) return formatDateTime(iso);
  const age = formatAge(alert.age_s);
  return age ? `Age ${age}` : "Not reported";
}

function alertReference(alert: AlertRow): string {
  switch (alert.kind) {
    case "webhook_dead_letter":
      return [alert.event_type, alert.paypal_event_id].filter(Boolean).join(" · ") || "Webhook event";
    case "authorization_aged":
      return (
        [alert.buyer_order_id, alert.paypal_auth_id]
          .filter((value): value is string => typeof value === "string")
          .map(shortId)
          .join(" · ") || "Buyer order"
      );
    default:
      return (
        [alert.lot_id, alert.pool_id]
          .filter((value): value is string => typeof value === "string")
          .map(shortId)
          .join(" · ") || "Lot"
      );
  }
}

export function AlertsPanel({
  alerts,
  loading,
  error,
  onRefresh,
}: {
  alerts: AlertRow[] | null;
  loading: boolean;
  error: { code: string; message: string } | null;
  onRefresh: () => void;
}) {
  return (
    <section className="panel ops-section" aria-labelledby="ops-alerts-heading">
      <div className="ops-section-head">
        <div>
          <h2 id="ops-alerts-heading">Open alerts</h2>
          <p>Dead letters, overdue lot deadlines, aged authorizations and lots stuck failing. Read-only.</p>
        </div>
        <button type="button" className="button-secondary ops-small-action" onClick={onRefresh} disabled={loading}>
          {loading ? "Refreshing…" : "Refresh"}
        </button>
      </div>
      <div className="ops-section-body">
        {error ? (
          <Notice kind="error" code={error.code}>
            {error.message}
          </Notice>
        ) : null}
        {loading && !alerts ? (
          <div className="ops-stack" role="status" aria-busy="true" aria-label="Loading alerts">
            <div className="skeleton ops-skeleton-row" />
            <div className="skeleton ops-skeleton-row" />
          </div>
        ) : null}
        {!loading && !error && alerts && alerts.length === 0 ? (
          <p className="ops-empty">
            No open alerts. Dead letters, overdue deadlines, aged authorizations and stuck failing lots
            appear here.
          </p>
        ) : null}
        {alerts && alerts.length > 0 ? (
          <div className="ops-table-wrap">
            <table className="ops-table">
              <thead>
                <tr>
                  <th scope="col">Severity</th>
                  <th scope="col">Alert</th>
                  <th scope="col">Reference</th>
                  <th scope="col">When</th>
                </tr>
              </thead>
              <tbody>
                {alerts.map((alert, index) => {
                  const severity = SEVERITY[alert.kind] ?? { label: "Watch", tone: "neutral" as const };
                  return (
                    <tr key={`${alert.kind}-${alert.event_id ?? alert.lot_id ?? alert.buyer_order_id ?? index}`}>
                      <td>
                        <StatusPill status={severity.label} tone={severity.tone} />
                      </td>
                      <td>
                        <span className="ops-cell-strong">{KIND_LABELS[alert.kind] ?? alert.kind}</span>
                        <code className="ops-cell-code" title={alert.kind}>{alert.kind}</code>
                      </td>
                      <td className="font-mono ops-cell-muted">{alertReference(alert)}</td>
                      <td className="ops-cell-muted">{alertWhen(alert)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : null}
      </div>
    </section>
  );
}
