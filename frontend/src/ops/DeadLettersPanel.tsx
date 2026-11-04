import { useCallback, useEffect, useState } from "react";

import { api, formatDateTime, Notice } from "../shared";

import { failureOf, type DeadLetterEvent } from "./api";

const LOAD_FAILED = "Dead-letter webhook events could not be loaded.";

export function DeadLettersPanel() {
  const [events, setEvents] = useState<DeadLetterEvent[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<{ code: string; message: string } | null>(null);
  const [retrying, setRetrying] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    void api
      .GET("/api/v1/admin/webhooks/dead-letter")
      .then(({ data, error: failure }) => {
        if (failure || !data) {
          setError(failureOf(failure, LOAD_FAILED));
          return;
        }
        const body = data as { events?: DeadLetterEvent[] };
        setEvents(Array.isArray(body.events) ? body.events : []);
      })
      .catch(() => setError({ code: "REQUEST_FAILED", message: `${LOAD_FAILED} Check your connection and try again.` }))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const retry = (event: DeadLetterEvent) => {
    if (retrying) return;
    setRetrying(event.id);
    setError(null);
    setNotice(null);
    void api
      .POST("/api/v1/admin/webhooks/{event_id}/retry", { params: { path: { event_id: event.id } } })
      .then(({ error: failure }) => {
        if (failure) {
          setError(failureOf(failure, "The event could not be re-queued."));
          return;
        }
        setNotice(`Retry enqueued for ${event.event_type}.`);
        load();
      })
      .catch(() => setError({ code: "REQUEST_FAILED", message: "The event could not be re-queued. Check your connection and try again." }))
      .finally(() => setRetrying(null));
  };

  return (
    <section className="panel ops-section" aria-labelledby="ops-dead-letter-heading">
      <div className="ops-section-head">
        <div>
          <h2 id="ops-dead-letter-heading">Dead-letter webhooks</h2>
          <p>
            Events that arrived but never applied. A retry re-drives the same row; PayPal&rsquo;s GET still decides
            the money state.
          </p>
        </div>
        <button type="button" className="button-secondary ops-small-action" onClick={load} disabled={loading}>
          {loading ? "Refreshing…" : "Refresh"}
        </button>
      </div>
      <div className="ops-section-body ops-stack">
        {error ? (
          <Notice kind="error" code={error.code}>
            {error.message}
          </Notice>
        ) : null}
        {notice ? <Notice kind="info">{notice}</Notice> : null}
        {loading && !events ? (
          <div role="status" aria-busy="true" aria-label="Loading dead-letter webhooks" className="ops-stack">
            <div className="skeleton ops-skeleton-row" />
            <div className="skeleton ops-skeleton-row" />
          </div>
        ) : null}
        {!loading && !error && events && events.length === 0 ? (
          <p className="ops-empty">
            No dead-letter events. Verified events that map cleanly never appear here.
          </p>
        ) : null}
        {events && events.length > 0 ? (
          <div className="ops-table-wrap">
            <table className="ops-table">
              <thead>
                <tr>
                  <th scope="col">Event</th>
                  <th scope="col">Status</th>
                  <th scope="col">Received</th>
                  <th scope="col">Detail</th>
                  <th scope="col">
                    <span className="sr-only">Action</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {events.map((event) => (
                  <tr key={event.id}>
                    <td>
                      <span className="ops-cell-strong font-mono">{event.event_type}</span>
                      <code className="ops-cell-code" title={event.paypal_event_id}>{event.paypal_event_id}</code>
                    </td>
                    <td>
                      <span className="ops-cell-strong">{event.status}</span>
                      <span className="ops-cell-muted">{event.verified ? "Signature verified" : "Not verified"}</span>
                    </td>
                    <td className="ops-cell-muted">{formatDateTime(event.received_at)}</td>
                    <td className="ops-cell-muted">{event.verification_detail ?? "No detail returned"}</td>
                    <td>
                      <button
                        type="button"
                        className="button-secondary ops-small-action"
                        aria-label={`Retry ${event.event_type} ${event.paypal_event_id}`}
                        disabled={retrying !== null}
                        onClick={() => retry(event)}
                      >
                        {retrying === event.id ? "Retrying…" : "Retry"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </div>
    </section>
  );
}
