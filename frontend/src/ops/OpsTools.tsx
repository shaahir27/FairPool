import { useEffect, useState } from "react";

import { api, formatDateTime, HonestyLabels, Notice } from "../shared";

import { failureOf, MOCK_KINDS, type MockKind, type MockToggle } from "./api";

type ActiveMock = { value: string | null; ttl_s: number; expiresAt: number };
type StoredMock = { kind: MockKind; value: string | null; expires_at: string };

const DEFAULT_TTL = "300";
/** Armed toggles survive a reload: the server keeps them until their TTL ends. */
const MOCK_STORAGE_KEY = "fairpool.ops.mockToggles";

function readArmed(): Partial<Record<MockKind, ActiveMock>> {
  const restored: Partial<Record<MockKind, ActiveMock>> = {};
  try {
    const raw = window.sessionStorage.getItem(MOCK_STORAGE_KEY);
    if (!raw) return restored;
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return restored;
    const now = Date.now();
    for (const item of parsed) {
      const row = item as Partial<StoredMock>;
      if (typeof row.kind !== "string" || !MOCK_KINDS.some((entry) => entry.kind === row.kind)) continue;
      const expiresAt = typeof row.expires_at === "string" ? Date.parse(row.expires_at) : Number.NaN;
      // An expired row is dropped here as well as on the server.
      if (!Number.isFinite(expiresAt) || expiresAt <= now) continue;
      restored[row.kind as MockKind] = {
        value: typeof row.value === "string" ? row.value : null,
        ttl_s: Math.max(1, Math.round((expiresAt - now) / 1000)),
        expiresAt,
      };
    }
  } catch {
    // A missing or unreadable store only costs this view its memory.
  }
  return restored;
}

function writeArmed(active: Partial<Record<MockKind, ActiveMock>>): void {
  try {
    const rows: StoredMock[] = Object.entries(active).flatMap(([kind, entry]) =>
      entry ? [{ kind: kind as MockKind, value: entry.value, expires_at: new Date(entry.expiresAt).toISOString() }] : [],
    );
    if (rows.length === 0) window.sessionStorage.removeItem(MOCK_STORAGE_KEY);
    else window.sessionStorage.setItem(MOCK_STORAGE_KEY, JSON.stringify(rows));
  } catch {
    // Storage can be blocked; the console still works for this view.
  }
}

export function ReconcilerPanel() {
  const [busy, setBusy] = useState(false);
  const [enqueued, setEnqueued] = useState<number | null>(null);
  const [ranWithoutCount, setRanWithoutCount] = useState(false);
  const [error, setError] = useState<{ code: string; message: string } | null>(null);

  const run = () => {
    if (busy) return;
    setBusy(true);
    setError(null);
    setEnqueued(null);
    setRanWithoutCount(false);
    void api
      .POST("/api/v1/admin/reconciler/run")
      .then(({ data, error: failure }) => {
        if (failure || !data) {
          setError(failureOf(failure, "The reconciler could not run."));
          return;
        }
        const count = (data as { enqueued?: unknown }).enqueued;
        if (typeof count === "number") setEnqueued(count);
        else setRanWithoutCount(true);
      })
      .catch(() => setError({ code: "REQUEST_FAILED", message: "The reconciler could not run. Check your connection and try again." }))
      .finally(() => setBusy(false));
  };

  return (
    <section className="panel ops-section" aria-labelledby="ops-reconciler-heading">
      <div className="ops-section-head">
        <div>
          <h2 id="ops-reconciler-heading">Reconciler</h2>
          <p>Re-queues the existing order.authorize and offer.expire triggers for stale orders. It never invents a transition.</p>
        </div>
      </div>
      <div className="ops-section-body ops-stack">
        <button type="button" className="button-secondary" onClick={run} disabled={busy}>
          {busy ? "Running…" : "Run reconciler now"}
        </button>
        {error ? (
          <Notice kind="error" code={error.code}>
            {error.message}
          </Notice>
        ) : null}
        {enqueued !== null ? (
          <Notice kind="info">
            {enqueued === 0 ? "Re-queued 0 stale orders. Nothing was stale." : `Re-queued ${enqueued} stale order${enqueued === 1 ? "" : "s"}.`}
          </Notice>
        ) : null}
        {ranWithoutCount ? (
          <Notice kind="info">The reconciler ran, but the server did not report a count.</Notice>
        ) : null}
      </div>
    </section>
  );
}

export function MockTogglesPanel() {
  const [values, setValues] = useState<Record<MockKind, string>>({
    paypal_mock_response: "",
    force_capture_failure: "",
    delay_webhooks: "",
  });
  const [ttls, setTtls] = useState<Record<MockKind, string>>({
    paypal_mock_response: DEFAULT_TTL,
    force_capture_failure: DEFAULT_TTL,
    delay_webhooks: DEFAULT_TTL,
  });
  const [active, setActive] = useState<Partial<Record<MockKind, ActiveMock>>>(readArmed);
  const [busy, setBusy] = useState<MockKind | null>(null);
  const [error, setError] = useState<{ code: string; message: string } | null>(null);

  // The MOCK label comes from this state, so a reload shows the same truth.
  useEffect(() => {
    writeArmed(active);
  }, [active]);

  // A toggle stops being visible when its own TTL runs out; the server arms it the same way.
  useEffect(() => {
    const expiries = Object.values(active).flatMap((entry) => (entry ? [entry.expiresAt] : []));
    if (expiries.length === 0) return;
    const next = Math.min(...expiries);
    const timer = window.setTimeout(() => {
      setActive((current) => {
        const now = Date.now();
        const kept = Object.entries(current).filter(([, entry]) => entry !== undefined && entry.expiresAt > now);
        return Object.fromEntries(kept) as Partial<Record<MockKind, ActiveMock>>;
      });
    }, Math.max(0, next - Date.now()));
    return () => window.clearTimeout(timer);
  }, [active]);

  const arm = (kind: MockKind) => {
    if (busy) return;
    const ttl = Number.parseInt(ttls[kind], 10);
    if (!Number.isFinite(ttl) || ttl < 1) {
      setError({ code: "VALIDATION_ERROR", message: "Enter a TTL of at least one second." });
      return;
    }
    setBusy(kind);
    setError(null);
    void api
      .POST("/api/v1/admin/mock", { body: { kind, value: values[kind].trim() || null, ttl_s: ttl } })
      .then(({ data, error: failure }) => {
        if (failure || !data) {
          const detail = failureOf(failure, "The mock toggle could not be armed.");
          setError(
            detail.code === "FEATURE_DISABLED"
              ? {
                  code: "FEATURE_DISABLED",
                  message: "Mock toggles are switched off on this deployment. Nothing was armed.",
                }
              : detail,
          );
          return;
        }
        const result = data as MockToggle;
        const seconds = typeof result.ttl_s === "number" ? result.ttl_s : ttl;
        setActive((current) => ({
          ...current,
          [kind]: { value: result.value ?? null, ttl_s: seconds, expiresAt: Date.now() + seconds * 1000 },
        }));
      })
      .catch(() => setError({ code: "REQUEST_FAILED", message: "The mock toggle could not be armed. Check your connection and try again." }))
      .finally(() => setBusy(null));
  };

  const armed = Object.values(active).filter((entry) => entry !== undefined);

  return (
    <section className="panel ops-section" aria-labelledby="ops-mock-heading">
      <div className="ops-section-head">
        <div>
          <h2 id="ops-mock-heading">Demo mock toggles</h2>
          <p>
            Mocks never enter the ordinary path, and any screen that shows mocked behaviour carries the MOCK
            label. Only available when the server enables them.
          </p>
        </div>
        {armed.length > 0 ? <HonestyLabels kinds={["mock"]} /> : null}
      </div>
      <div className="ops-section-body ops-stack">
        {error ? (
          <Notice kind={error.code === "FEATURE_DISABLED" ? "warn" : "error"} code={error.code}>
            {error.message}
          </Notice>
        ) : null}
        {MOCK_KINDS.map((item) => {
          const entry = active[item.kind];
          return (
            <div key={item.kind} className="ops-mock-row">
              <div>
                <p className="ops-cell-strong">{item.label}</p>
                <p className="ops-note">{item.hint}</p>
              </div>
              <div className="ops-field-row">
                <label className="ops-field" htmlFor={`ops-mock-value-${item.kind}`}>
                  Value (optional)
                  <input
                    id={`ops-mock-value-${item.kind}`}
                    className="form-input"
                    value={values[item.kind]}
                    onChange={(event) =>
                      setValues((current) => ({ ...current, [item.kind]: event.target.value }))
                    }
                    spellCheck={false}
                  />
                </label>
                <label className="ops-field" htmlFor={`ops-mock-ttl-${item.kind}`}>
                  TTL (s)
                  <input
                    id={`ops-mock-ttl-${item.kind}`}
                    className="form-input"
                    inputMode="numeric"
                    value={ttls[item.kind]}
                    onChange={(event) => setTtls((current) => ({ ...current, [item.kind]: event.target.value }))}
                  />
                </label>
                <button
                  type="button"
                  className="button-secondary"
                  aria-label={`Arm ${item.label}`}
                  disabled={busy !== null}
                  onClick={() => arm(item.kind)}
                >
                  {busy === item.kind ? "Arming…" : "Arm"}
                </button>
              </div>
              {entry ? (
                <div className="ops-mock-active" role="status">
                  <HonestyLabels kinds={["mock"]} />
                  <span>Armed until {formatDateTime(new Date(entry.expiresAt).toISOString())}</span>
                </div>
              ) : null}
            </div>
          );
        })}
        <p className="ops-note">
          Armed toggles are kept for this tab&rsquo;s session, so a reload still shows them until their TTL
          ends. A toggle applies to the process serving the request; captures run in the worker.
        </p>
      </div>
    </section>
  );
}

export function AuditExportPanel() {
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<{ code: string; message: string } | null>(null);

  const exportChain = () => {
    if (busy) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    void api
      .GET("/api/v1/admin/audit/export")
      .then(({ data, error: failure }) => {
        if (failure || !data) {
          setError(failureOf(failure, "The audit chain could not be exported."));
          return;
        }
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
        const url = URL.createObjectURL(blob);
        const anchor = document.createElement("a");
        anchor.href = url;
        anchor.download = "audit-export.json";
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
        URL.revokeObjectURL(url);
        const count = Array.isArray(data.checkpoints) ? data.checkpoints.length : 0;
        setNotice(`Downloaded audit-export.json with ${count} checkpoint${count === 1 ? "" : "s"}.`);
      })
      .catch(() => setError({ code: "REQUEST_FAILED", message: "The audit chain could not be exported. Check your connection and try again." }))
      .finally(() => setBusy(false));
  };

  return (
    <section className="panel ops-section" aria-labelledby="ops-audit-heading">
      <div className="ops-section-head">
        <div>
          <h2 id="ops-audit-heading">Audit export</h2>
          <p>The chained audit checkpoints as JSON. The file is built in the browser from the server response.</p>
        </div>
      </div>
      <div className="ops-section-body ops-stack">
        <button type="button" className="button-secondary" onClick={exportChain} disabled={busy}>
          {busy ? "Exporting…" : "Export audit chain"}
        </button>
        {error ? (
          <Notice kind="error" code={error.code}>
            {error.message}
          </Notice>
        ) : null}
        {notice ? <Notice kind="info">{notice}</Notice> : null}
      </div>
    </section>
  );
}
