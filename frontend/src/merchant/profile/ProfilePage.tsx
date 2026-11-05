import { type FormEvent, useEffect, useState } from "react";

import {
  api,
  type ApiComponents,
  formatDateTime,
  HONESTY_LABELS,
  HonestyLabels,
  Notice,
  StatusPill,
} from "../../shared";
import { failureEnvelope } from "../lib";

type ProfileResponse = ApiComponents["schemas"]["MerchantProfileResponse"];

const ATTESTATIONS: ReadonlyArray<{ key: string; label: string }> = [
  {
    key: "inventory_reserved",
    label: "Inventory is reserved for the quantities I bid.",
  },
  {
    key: "map_compliance",
    label: "My prices comply with the minimum advertised price rules that apply to me.",
  },
  {
    key: "delivery_terms_accurate",
    label: "Delivery and return terms in my bids are accurate.",
  },
];

type AttestationState = Record<string, boolean>;

function accepted(value: unknown): boolean {
  return (
    typeof value === "object" &&
    value !== null &&
    (value as { accepted?: unknown }).accepted === true
  );
}

function stamp(value: unknown): string | null {
  if (typeof value !== "object" || value === null) return null;
  const at = (value as { at?: unknown }).at;
  return typeof at === "string" ? at : null;
}

/**
 * FR-AU-01/03: the merchant row, the three self-declarations and the status the
 * server stamped on creation. This form cannot move onboarding_status, and does
 * not imply that it can.
 */
export function ProfilePage() {
  const [displayName, setDisplayName] = useState("");
  const [payeeEmail, setPayeeEmail] = useState("");
  const [paypalMerchantId, setPaypalMerchantId] = useState("");
  const [attestations, setAttestations] = useState<AttestationState>(() =>
    Object.fromEntries(ATTESTATIONS.map((row) => [row.key, false])),
  );
  // Only fields the merchant touched are sent; an untouched field keeps what the
  // server already holds (the POST merges by `model_fields_set`).
  const [edited, setEdited] = useState<ReadonlySet<string>>(new Set());
  const [prefillProblem, setPrefillProblem] = useState("");
  const [prefillLoading, setPrefillLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [problem, setProblem] = useState<{ code: string; message: string } | null>(null);
  const [result, setResult] = useState<ProfileResponse | null>(null);

  useEffect(() => {
    let live = true;
    void api
      .GET("/api/v1/me")
      .then(({ data, error: failure }) => {
        if (!live) return;
        if (data?.display_name) {
          // Keep anything the merchant has already typed.
          setDisplayName((current) => current || data.display_name);
        } else if (failure) {
          setPrefillProblem("Your account name could not be loaded. Enter it below.");
        }
      })
      .catch(() => {
        if (live) setPrefillProblem("Your account name could not be loaded. Enter it below.");
      })
      .finally(() => {
        if (live) setPrefillLoading(false);
      });
    return () => {
      live = false;
    };
  }, []);

  function noteEdited(field: string) {
    setEdited((current) => (current.has(field) ? current : new Set(current).add(field)));
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (saving) return;
    const name = displayName.trim();
    if (!name) {
      setProblem({ code: "VALIDATION_ERROR", message: "Enter the display name offers will carry." });
      return;
    }
    setSaving(true);
    setProblem(null);
    try {
      const body: {
        display_name: string;
        payee_email?: string | null;
        paypal_merchant_id?: string | null;
        attestations?: Record<string, { accepted: boolean }>;
      } = { display_name: name };
      if (edited.has("payee_email")) body.payee_email = payeeEmail.trim() || null;
      if (edited.has("paypal_merchant_id")) body.paypal_merchant_id = paypalMerchantId.trim() || null;
      const touched = ATTESTATIONS.filter((row) => edited.has(row.key));
      if (touched.length > 0) {
        body.attestations = Object.fromEntries(
          touched.map((row) => [row.key, { accepted: Boolean(attestations[row.key]) }]),
        );
      }
      const { data, error: failure } = await api.POST("/api/v1/merchant/profile", { body });
      if (failure || !data) {
        setProblem(failureEnvelope(failure));
        return;
      }
      setResult(data);
      setEdited(new Set());
      setAttestations(
        Object.fromEntries(
          ATTESTATIONS.map((row) => [row.key, accepted(data.attestations[row.key])]),
        ),
      );
    } catch {
      setProblem({
        code: "REQUEST_FAILED",
        message: "Check your connection and save the profile again.",
      });
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="merchant-page">
      <header className="merchant-heading">
        <div>
          <h1 className="shop-title">Merchant profile</h1>
          <p className="shop-copy mt-2">
            The name offers carry, the payee details PayPal checks, and the three
            declarations behind every bid.
          </p>
        </div>
      </header>

      {prefillLoading ? (
        <p className="shop-copy" role="status">
          Loading your account name.
        </p>
      ) : null}
      {prefillProblem ? (
        <Notice kind="warn">{prefillProblem}</Notice>
      ) : null}

      <div className="merchant-profile-grid">
        <section className="shop-panel" aria-labelledby="profile-form-title">
          <div className="panel-band">
            <h2 id="profile-form-title">Merchant record</h2>
          </div>
          <div className="shop-panel-pad">
            <form onSubmit={(event) => void save(event)}>
              <label className="merchant-field" htmlFor="profile-name">
                Display name
              </label>
              <input
                id="profile-name"
                className="form-input"
                value={displayName}
                maxLength={120}
                onChange={(event) => setDisplayName(event.target.value)}
              />

              <label className="merchant-field mt-4" htmlFor="profile-payee-email">
                Payee email (optional)
              </label>
              <input
                id="profile-payee-email"
                type="email"
                className="form-input"
                value={payeeEmail}
                maxLength={254}
                aria-describedby="profile-kept-help"
                onChange={(event) => {
                  setPayeeEmail(event.target.value);
                  noteEdited("payee_email");
                }}
              />

              <label className="merchant-field mt-4" htmlFor="profile-merchant-id">
                PayPal merchant ID (optional)
              </label>
              <input
                id="profile-merchant-id"
                className="form-input"
                value={paypalMerchantId}
                maxLength={64}
                aria-describedby="profile-kept-help"
                onChange={(event) => {
                  setPaypalMerchantId(event.target.value);
                  noteEdited("paypal_merchant_id");
                }}
              />
              <p id="profile-kept-help" className="merchant-help">
                Leave a payee field blank to keep the value already saved. Only the fields you
                change are sent, so an attestation you do not touch keeps its existing record.
              </p>

              <fieldset className="merchant-attestations">
                <legend className="merchant-field">Attestations</legend>
                {ATTESTATIONS.map((row) => (
                  <label key={row.key} className="merchant-check">
                    <input
                      type="checkbox"
                      checked={Boolean(attestations[row.key])}
                      onChange={(event) => {
                        setAttestations((current) => ({
                          ...current,
                          [row.key]: event.target.checked,
                        }));
                        noteEdited(row.key);
                      }}
                    />
                    <span>{row.label}</span>
                  </label>
                ))}
              </fieldset>
              <p className="merchant-help">
                Creating an API key requires all three attestations accepted.
              </p>

              {problem ? (
                <div className="mt-4">
                  <Notice kind="error" code={problem.code}>
                    {problem.message}
                  </Notice>
                </div>
              ) : null}

              <div className="merchant-actions">
                <button type="submit" className="button-primary" disabled={saving}>
                  {saving ? "Saving…" : "Save profile"}
                </button>
              </div>
            </form>
          </div>
        </section>

        <section className="shop-panel" aria-labelledby="profile-status-title">
          <div className="panel-band">
            <h2 id="profile-status-title">Onboarding status</h2>
          </div>
          <div className="shop-panel-pad">
            {result ? (
              <div className="merchant-result">
                <div className="merchant-result-status" role="status">
                  <StatusPill status={result.onboarding_status}>
                    {result.onboarding_status}
                  </StatusPill>
                  <span className="shop-copy">{result.display_name}</span>
                </div>
                <p className="merchant-help mt-3">
                  Onboarding status is set when the merchant row is created; this form
                  does not change it.
                </p>
                {result.onboarding_status === "DEMO" ? (
                  <div className="merchant-demo mt-4">
                    <p>{HONESTY_LABELS.fallbackSentence}</p>
                    <HonestyLabels kinds={["fallback"]} />
                  </div>
                ) : null}
                <p className="merchant-label mt-4">Merchant ID</p>
                <code className="merchant-hash">{result.merchant_id}</code>
                <p className="merchant-label mt-4">Attestations on record</p>
                <ul className="merchant-attestation-list">
                  {ATTESTATIONS.map((row) => {
                    const value = result.attestations[row.key];
                    const at = stamp(value);
                    return (
                      <li key={row.key}>
                        <div>
                          <strong>{row.key}</strong>
                          <span>{accepted(value) ? "Accepted" : "Not accepted"}</span>
                        </div>
                        {at ? <time dateTime={at}>{formatDateTime(at)}</time> : null}
                      </li>
                    );
                  })}
                </ul>
              </div>
            ) : (
              <p className="shop-copy">
                Save the profile to see the status and attestations the server records.
              </p>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
