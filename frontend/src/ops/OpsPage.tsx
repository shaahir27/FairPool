import { Navigate, useLocation, useSearchParams } from "react-router-dom";

import { api, useApiRead, AreaLayout, Icon, type AreaTab } from "../shared";

import { AlertsPanel } from "./AlertsPanel";
import { DeadLettersPanel } from "./DeadLettersPanel";
import { LotPanel } from "./LotPanel";
import { AuditExportPanel, MockTogglesPanel, ReconcilerPanel } from "./OpsTools";
import { failureOf, type AlertRow } from "./api";
import "./ops.css";

const OPS_TABS: readonly AreaTab[] = [
  { to: "/ops", label: "Overview", end: true },
  { to: "/ops/lots", label: "Lots", end: false },
  { to: "/ops/recovery", label: "Recovery", end: false },
  { to: "/ops/audit", label: "Audit trail", end: false },
];
const OPS_UTILITIES = [{ to: "/ops/sandbox", label: "Sandbox controls" }];
const VIEWS: Record<string, { title: string; description: string }> = {
  "/ops": { title: "Ops console", description: "The alerts that need your attention, and the lots behind them." },
  "/ops/lots": { title: "Lot operations", description: "Inspect a lot's state and payment configuration. Abort only when intervention is needed." },
  "/ops/recovery": { title: "Recovery", description: "Review failed webhook events and re-queue stale order checks." },
  "/ops/audit": { title: "Audit trail", description: "Export the recorded checkpoints for review outside FairPool." },
  "/ops/sandbox": { title: "Sandbox controls", description: "Deliberate failure injection for the demo. These controls are separate from normal operations." },
};

export function OpsPage() {
  const { pathname } = useLocation();
  const [params] = useSearchParams();
  const path = pathname.replace(/\/$/, "");
  const view = VIEWS[path];
  const records = useApiRead("/api/v1/admin/alerts", (signal) => api.GET("/api/v1/admin/alerts", {signal}), {enabled: path === "/ops" || path === "/ops/lots"});
  const body = records.data as {alerts?: AlertRow[]} | undefined;
  const alerts = body ? (Array.isArray(body.alerts) ? body.alerts : []) : null;
  const loading = records.isPending || records.isFetching;
  const error = records.error ? failureOf(records.error, "Alerts could not be loaded. Try refreshing.") : null;
  const loadAlerts = () => { void records.refetch(); };

  if (!view) return <Navigate to="/ops" replace />;
  const alertLots = [...new Set((alerts ?? []).flatMap((alert) => alert.lot_id ? [alert.lot_id] : []))];
  const urgent = (alerts ?? []).filter((alert) => ["webhook_dead_letter", "lot_past_fund_deadline", "lot_failing"].includes(alert.kind)).length;
  const known = alerts !== null && !error;

  return <AreaLayout workspace="Ops console" tabs={OPS_TABS} utilityLinks={OPS_UTILITIES}>
    <div className="ops-page" data-ui="admin">
      <header className="ops-heading"><h1>{view.title}</h1><p>{view.description}</p></header>

      {path === "/ops" && <>
        <section className="ops-summary" aria-label="Open alert summary" aria-busy={loading}>
          <div className="ops-summary-finding"><Icon name={known && urgent === 0 ? "check" : "info"} /><div>
            <strong>{!known ? (error ? "Alert overview unavailable" : "Checking open alerts…") : urgent > 0 ? `${urgent} alert${urgent === 1 ? " needs" : "s need"} action` : "No urgent alerts reported"}</strong>
            <p>{error ? "Refresh the alerts below, or continue to another admin page." : loading && alerts ? "Refreshing. Counts show the previous response." : "From the latest alert response. This is not a full system-health check."}</p>
          </div></div>
          <dl>
            <div><dt>Requires action</dt><dd>{known ? urgent : "—"}</dd></div>
            <div><dt>Under watch</dt><dd>{known ? alerts.length - urgent : "—"}</dd></div>
            <div><dt>Lots with alerts</dt><dd>{known ? alertLots.length : "—"}</dd></div>
          </dl>
        </section>
        <div className="ops-overview-grid">
          <AlertsPanel alerts={alerts} loading={loading} error={error} onRefresh={loadAlerts} />

        </div>
      </>}

      {path === "/ops/lots" && <div className="ops-lot-layout"><LotPanel key={params.get("lot_id")} alertLots={alertLots} initialLotId={params.get("lot_id") ?? undefined} /></div>}
      {path === "/ops/recovery" && <div className="ops-recovery-grid"><DeadLettersPanel /><ReconcilerPanel /></div>}
      {path === "/ops/audit" && <div className="ops-audit-layout"><AuditExportPanel /></div>}
      {path === "/ops/sandbox" && <MockTogglesPanel />}
    </div>
  </AreaLayout>;
}
