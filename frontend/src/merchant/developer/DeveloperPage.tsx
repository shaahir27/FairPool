import { type FormEvent, useState } from "react";

import {
  api,
  useApiRead,
  type ApiComponents,
  formatDateTime,
  Icon,
  Notice,
  StatusPill,
} from "../../shared";
import { failureEnvelope } from "../lib";

type ApiKeyView = ApiComponents["schemas"]["ApiKeyView"];
type ApiKeyCreated = ApiComponents["schemas"]["ApiKeyCreated"];

const SCOPES: ReadonlyArray<{ id: string; label: string }> = [
  { id: "lots:read", label: "Read open lots" },
  { id: "bids:read", label: "Read bids" },
  { id: "bids:write", label: "Submit bids" },
  { id: "fulfillment:read", label: "Read fulfillment rows" },
  { id: "shipments:write", label: "Record shipments" },
  { id: "manifest:read", label: "Read verification manifest" },
];

/**
 * FR-UI-07: keys are created here, shown once, listed by prefix and revoked.
 * The secret is never fetched again; the row keeps only its HMAC server-side.
 */
export function DeveloperPage() {
  const records = useApiRead("/api/v1/merchant/api-keys", (signal) => api.GET("/api/v1/merchant/api-keys", {signal}));
  const keys: ApiKeyView[] | null = records.data?.items ?? null;
  const loading = records.isPending;
  const error = records.error ? failureEnvelope(records.error) : null;
  const [name, setName] = useState("");
  const [scopes, setScopes] = useState<string[]>(["lots:read", "bids:read"]);
  const [creating, setCreating] = useState(false);
  const [createProblem, setCreateProblem] = useState<{ code: string; message: string } | null>(null);
  const [secret, setSecret] = useState<ApiKeyCreated | null>(null);
  const [copied, setCopied] = useState(false);
  const [copyProblem, setCopyProblem] = useState("");
  const [revoking, setRevoking] = useState<string | null>(null);
  const [revokeBusy, setRevokeBusy] = useState<string | null>(null);
  const [revokedNow, setRevokedNow] = useState<string[]>([]);
  const [revokeProblem, setRevokeProblem] = useState<{ code: string; message: string } | null>(null);


  async function createKey(event: FormEvent) {
    event.preventDefault();
    const trimmed = name.trim();
    if (!trimmed || scopes.length === 0 || creating) return;
    setCreating(true);
    setCreateProblem(null);
    setCopied(false);
    setCopyProblem("");
    try {
      const { data, error: failure } = await api.POST("/api/v1/merchant/api-keys", {
        body: { name: trimmed, scopes },
      });
      if (failure || !data) {
        setCreateProblem(failureEnvelope(failure));
        return;
      }
      setSecret(data);
      setName("");
      void records.refetch({cancelRefetch: false});
    } catch {
      setCreateProblem({
        code: "REQUEST_FAILED",
        message: "Check your connection and create the key again.",
      });
    } finally {
      setCreating(false);
    }
  }

  async function copySecret() {
    if (!secret) return;
    try {
      if (!navigator.clipboard?.writeText) throw new Error("clipboard unavailable");
      await navigator.clipboard.writeText(secret.key);
      setCopied(true);
      setCopyProblem("");
    } catch {
      setCopied(false);
      setCopyProblem("The key could not be copied. Select it and copy it manually.");
    }
  }

  async function revokeKey(id: string) {
    if (revokeBusy) return;
    setRevokeBusy(id);
    setRevokeProblem(null);
    try {
      const { error: failure } = await api.DELETE("/api/v1/merchant/api-keys/{key_id}", {
        params: { path: { key_id: id } },
      });
      if (failure) {
        setRevokeProblem(failureEnvelope(failure));
        return;
      }
      // The DELETE returns no new timestamp; never stamp one from the browser clock.
      setRevokedNow((current) => (current.includes(id) ? current : [...current, id]));
      setRevoking(null);
    } catch {
      setRevokeProblem({
        code: "REQUEST_FAILED",
        message: "Check your connection. The key may still be active.",
      });
    } finally {
      setRevokeBusy(null);
    }
  }

  return (
    <div className="merchant-page">
      <header className="merchant-heading">
        <div>
          <h1 className="shop-title">Developer API</h1>
          <p className="shop-copy mt-2">
            Keys for the Merchant Agent API. A key carries only the scopes you grant it,
            and the secret is shown once.
          </p>
        </div>
      </header>

      <div className="merchant-developer-grid">
        <section className="shop-panel" aria-labelledby="create-key-title">
          <div className="panel-band">
            <h2 id="create-key-title">Create a key</h2>
          </div>
          <div className="shop-panel-pad">
            <form onSubmit={(event) => void createKey(event)}>
              <label className="merchant-field" htmlFor="key-name">
                Key name
              </label>
              <input
                id="key-name"
                className="form-input"
                value={name}
                maxLength={120}
                placeholder="For example, pricing-bot"
                onChange={(event) => setName(event.target.value)}
              />
              <fieldset className="merchant-scopes">
                <legend className="merchant-field">Scopes</legend>
                {SCOPES.map((scope) => (
                  <label key={scope.id} className="merchant-check">
                    <input
                      type="checkbox"
                      checked={scopes.includes(scope.id)}
                      onChange={() =>
                        setScopes((current) =>
                          current.includes(scope.id)
                            ? current.filter((value) => value !== scope.id)
                            : [...current, scope.id],
                        )
                      }
                    />
                    <span>{scope.label}</span>
                    <code className="merchant-code">{scope.id}</code>
                  </label>
                ))}
              </fieldset>
              {createProblem ? (
                <div className="mt-4">
                  <Notice kind="error" code={createProblem.code}>
                    {createProblem.message}
                  </Notice>
                </div>
              ) : null}
              <div className="merchant-actions">
                <button
                  type="submit"
                  className="button-primary"
                  disabled={creating || !name.trim() || scopes.length === 0}
                >
                  {creating ? "Creating…" : "Create key"}
                </button>
              </div>
              <p className="merchant-help">
                Creating a key requires all three profile attestations to be accepted.
              </p>
            </form>

            {secret ? (
              <section className="merchant-secret" aria-labelledby="secret-title">
                <h3 id="secret-title">{secret.name}: your new key</h3>
                <p className="merchant-warning">
                  This key is shown once. Store it now — FairPool cannot show it again.
                </p>
                <code className="merchant-secret-value">{secret.key}</code>
                <div className="merchant-actions">
                  <button
                    type="button"
                    className="button-secondary"
                    onClick={() => void copySecret()}
                  >
                    <Icon name="copy" />
                    {copied ? "Key copied" : "Copy key"}
                  </button>
                  <button
                    type="button"
                    className="shop-quiet-button"
                    onClick={() => {
                      setSecret(null);
                      setCopied(false);
                      setCopyProblem("");
                    }}
                  >
                    Hide key
                  </button>
                </div>
                {copyProblem ? <p className="merchant-warning">{copyProblem}</p> : null}
              </section>
            ) : null}
          </div>
        </section>

        <section className="shop-panel" aria-labelledby="keys-title">
          <div className="panel-band">
            <h2 id="keys-title">Your keys</h2>
          </div>
          <div className="shop-panel-pad">
            {error ? (
              <Notice kind="error" code={error.code}>
                {error.message}{" "}
                <button
                  type="button"
                  className="merchant-link"
                  onClick={() => void records.refetch({cancelRefetch: false})}
                >
                  Reload keys
                </button>
              </Notice>
            ) : null}
            {revokeProblem ? (
              <div className="mb-4">
                <Notice kind="error" code={revokeProblem.code}>
                  {revokeProblem.message}
                </Notice>
              </div>
            ) : null}
            {loading && keys === null ? (
              <p className="shop-copy" role="status">
                Loading your API keys.
              </p>
            ) : keys && keys.length > 0 ? (
              <ul className="merchant-key-list" aria-label="Your API keys">
                {keys.map((key) => {
                  const revoked = Boolean(key.revoked_at) || revokedNow.includes(key.id);
                  return (
                    <li key={key.id}>
                      <article className="merchant-key">
                        <div className="merchant-key-head">
                          <div>
                            <h3>{key.name}</h3>
                            <code className="merchant-code">{key.key_prefix}</code>
                          </div>
                          {revoked ? (
                            <StatusPill status="REVOKED" tone="bad">
                              Revoked
                            </StatusPill>
                          ) : (
                            <StatusPill status="ACTIVE" tone="good">
                              Active
                            </StatusPill>
                          )}
                        </div>
                        <p className="merchant-help">
                          Scopes: {key.scopes.join(", ") || "None"} · Last used:{" "}
                          {key.last_used_at ? formatDateTime(key.last_used_at) : "Never"}
                        </p>
                        {revoked && key.revoked_at ? (
                          <p className="merchant-help">
                            Revoked {formatDateTime(key.revoked_at)}
                          </p>
                        ) : null}
                        {revoking === key.id ? (
                          <div className="merchant-revoke-confirm">
                            <p>Revoke this key? Requests using it will fail immediately.</p>
                            <div className="merchant-actions">
                              <button
                                type="button"
                                className="button-primary"
                                disabled={revokeBusy === key.id}
                                onClick={() => void revokeKey(key.id)}
                              >
                                {revokeBusy === key.id ? "Revoking…" : "Confirm revoke"}
                              </button>
                              <button
                                type="button"
                                className="shop-quiet-button"
                                disabled={revokeBusy === key.id}
                                onClick={() => setRevoking(null)}
                              >
                                Keep key
                              </button>
                            </div>
                          </div>
                        ) : !revoked ? (
                          <div className="merchant-actions">
                            <button
                              type="button"
                              className="shop-quiet-button"
                              aria-label={`Revoke ${key.name}`}
                              onClick={() => setRevoking(key.id)}
                            >
                              Revoke
                            </button>
                          </div>
                        ) : null}
                      </article>
                    </li>
                  );
                })}
              </ul>
            ) : (
              <div className="catalogue-empty">
                <Icon name="lock" />
                <p>No API keys yet. Create one to use the Merchant Agent API.</p>
              </div>
            )}

            <div className="merchant-sdk">
              <h3 className="merchant-subheading">SDK and reference</h3>
              <p className="merchant-help">
                The SDK is generated from this document; it is not hand-written here.
              </p>
              <a
                className="merchant-link"
                href="/merchant-api/v1/openapi.json"
                target="_blank"
                rel="noreferrer"
              >
                Merchant API OpenAPI document
              </a>
              <p className="merchant-label mt-4">Rate limit</p>
              <p className="merchant-help">120 requests per minute per key.</p>
              <p className="merchant-label mt-4">Quickstart</p>
              <pre className="merchant-quickstart">
                <code>
                  {`curl -H "Authorization: Bearer fpm_..." \\\n  ${typeof window === "undefined" ? "" : window.location.origin}/merchant-api/v1/lots`}
                </code>
              </pre>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
