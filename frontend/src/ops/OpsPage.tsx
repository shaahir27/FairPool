import { useCallback, useEffect, useMemo, useState } from "react";

import { api, AreaLayout, type AreaTab } from "../shared";

import { AlertsPanel } from "./AlertsPanel";
import { DeadLettersPanel } from "./DeadLettersPanel";
import { LotPanel } from "./LotPanel";
import { AuditExportPanel, MockTogglesPanel, ReconcilerPanel } from "./OpsTools";
import { failureOf, type AlertRow } from "./api";
import "./ops.css";

const OPS_TABS: readonly AreaTab[] = [
  { to: "/ops", label: "Overview", end: false },
];

const ALERTS_FAILED = "Alerts could not be loaded. The rest of the console still works.";

export function OpsPage() {
  const [alerts, setAlerts] = useState<AlertRow[] | null>(null);
  const [alertsLoading, setAlertsLoading] = useState(true);
  const [alertsError, setAlertsError] = useState<{ code: string; message: string } | null>(null);

  const loadAlerts = useCallback(() => {
    setAlertsLoading(true);
    setAlertsError(null);
    void api
      .GET("/api/v1/admin/alerts")
      .then(({ data, error: failure }) => {
        if (failure || !data) {
          setAlertsError(failureOf(failure, ALERTS_FAILED));
          return;
        }
        const body = data as { alerts?: AlertRow[] };
        setAlerts(Array.isArray(body.alerts) ? body.alerts : []);
      })
      .catch(() => setAlertsError({ code: "REQUEST_FAILED", message: `${ALERTS_FAILED} Check your connection and try again.` }))
      .finally(() => setAlertsLoading(false));
  }, []);

  useEffect(() => {
    loadAlerts();
  }, [loadAlerts]);

  const alertLots = useMemo(
    () => (alerts ?? []).flatMap((alert) => (typeof alert.lot_id === "string" ? [alert.lot_id] : [])),
    [alerts],
  );

  return (
    <AreaLayout workspace="Ops console" tabs={OPS_TABS}>
      <div className="ops-page">
        <header className="ops-heading">
          <h1>Ops console</h1>
          <p>
            Look up a lot, watch open alerts, retry dead-letter webhooks, run the reconciler, arm demo mocks
            and export the audit chain. Every lot change goes through the state machine and is audited.
          </p>
        </header>

        <div className="ops-columns">
          <LotPanel alertLots={alertLots} />
          <AlertsPanel
            alerts={alerts}
            loading={alertsLoading}
            error={alertsError}
            onRefresh={loadAlerts}
          />
        </div>

        <div className="ops-block">
          <DeadLettersPanel />
        </div>

        <div className="ops-tools">
          <ReconcilerPanel />
          <MockTogglesPanel />
          <AuditExportPanel />
        </div>
      </div>
    </AreaLayout>
  );
}
