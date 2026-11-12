import { type FormEvent, lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";

import {
  accountState,
  API_BASE_URL,
  StatusPill,
  api,
  useApiRead,
  type ApiComponents,
  envelope,
  formatCents,
  formatDateTime,
  Icon,
  Notice,
  resetSessionCache,
  setCsrfToken,
  setAccount,
  workspaceHome,
  workspaceRole,
} from "../shared";
const OrderStatusCard = lazy(() => import("../checkout").then((module) => ({ default: module.OrderStatusCard })));

import { AuthFrame } from "./AuthFrame";
import { resetBuyerPrefetch } from "./prefetch";
import { ConfirmAction } from "./ConfirmAction";
import { usdToCents } from "./lobby/money";
import "./settings.css";
import "./agents.css";
import { decideAuthorization, type Authorization } from "./agentOAuth";
export { MyPoolsPage } from "./my-pools/MyPoolsPage";
export { OrdersPage } from "./orders/OrdersPage";
export { RegisterPage } from "./signup";

export function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const merchant = new URLSearchParams(location.search).get("role") === "merchant";
  const from = (location.state as { from?: string } | null)?.from;
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ code: string; message: string } | null>(null);

  useEffect(() => {
    document.documentElement.scrollTop = 0;
  }, []);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { data, error: failure } = await api.POST("/api/v1/auth/login", { body: { email, password } });
      if (failure || !data) { setError(envelope(failure)); return; }
      setCsrfToken(data.csrf_token);
      resetSessionCache();
      // A new sign-in may be a different person on the same browser.
      resetBuyerPrefetch();
      const { data: me, error: accountFailure } = await api.GET("/api/v1/me");
      if (accountFailure || !me) { setError(envelope(accountFailure)); return; }
      const home = workspaceHome(me.role);
      if (!home) { setError({ code: "FORBIDDEN", message: "Account access unavailable. Contact the FairPool operator." }); return; }
      setAccount({ display_name: typeof me.display_name === "string" ? me.display_name.trim() : "", role: me.role, paypal_linked: me.paypal_linked === true });
      resetSessionCache("in");
      navigate(typeof from === "string" && workspaceRole(from) === me.role ? from : home, { replace: true });
    } catch {
      setError({ code: "REQUEST_FAILED", message: "Check your connection and try again." });
    } finally { setBusy(false); }
  };

  return (
    <AuthFrame
      headline={merchant ? "Bid for a whole group of buyers." : "Join together. Let merchants compete for your group."}
      valueLine={merchant ? "Find group demand and submit your best delivered price in a sealed auction." : "Join a pool for free. Merchants bid in a sealed auction, and you approve your own payment."}
    >
      <Link className="signup-back inline-block mb-4" to="/">Back to landing page</Link>
      <h1 className="auth-title">Sign in</h1>
      <p className="mt-2 text-sm text-muted">{merchant ? "Sign in to your merchant workspace." : "Sign in to your buyer workspace."}</p>
      {error ? (
        <div className="mt-4">
          <Notice kind="error" code={error.code}>
            {error.message}
          </Notice>
        </div>
      ) : null}
      <form className="auth-fields" onSubmit={(event) => void submit(event)}>
        <label className="block">
          <span className="text-sm font-medium">Email</span>
          <input
            placeholder="Your email address"
            type="email"
            required
            autoComplete="email"
            className="form-input"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
        </label>
        <label className="block">
          <span id="password-label" className="text-sm font-medium">Password</span>
          <span className="password-field">
            <input
              placeholder="Your password"
              type={show ? "text" : "password"}
              required
              autoComplete="current-password"
              className="form-input"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
            <button
              type="button"
              className="password-toggle"
              aria-label={show ? "Hide password" : "Show password"}
              aria-pressed={show}
              onClick={() => setShow((value) => !value)}
            >
              <Icon name="eye" />
            </button>
          </span>
        </label>
        <button
          type="submit"
          disabled={busy}
          className="button-primary w-full"
        >
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
      {!merchant && <p className="auth-switch">
        New to FairPool?{" "}
        <Link className="font-semibold underline decoration-accent decoration-2 underline-offset-4" to="/register">
          Create account
        </Link>
      </p>}
    </AuthFrame>
  );
}

export function BuyerOrderPage() {
  const { buyerOrderId } = useParams<{ buyerOrderId: string }>();
  if (!buyerOrderId) {
    return <p className="p-6 text-sm text-muted">This order link is incomplete.</p>;
  }
  return <Suspense fallback={<p role="status">Loading your order…</p>}><OrderStatusCard buyerOrderId={buyerOrderId} /></Suspense>;
}

/** Linking finishes on the API callback, so the page opens it in a popup and watches /me. */
export function PayPalSettingsPage() {
  const [confirming, setConfirming] = useState(false);
  const [linked, setLinked] = useState<boolean | null>(null);
  const updateLinked = useCallback((value: boolean) => {
    setLinked(value);
    const current = accountState();
    if (current) setAccount({ ...current, paypal_linked: value });
  }, []);
  const [error, setError] = useState<{ code: string; message: string } | null>(null);
  const [busy, setBusy] = useState<"link" | "unlink" | null>(null);
  const [attempt, setAttempt] = useState(0);
  const poll = useRef<number | null>(null);
  const popup = useRef<Window | null>(null);

  function stopPolling() {
    if (poll.current !== null) {
      window.clearInterval(poll.current);
      poll.current = null;
    }
  }

  // Navigating away must not leave a poll (or a PayPal popup) behind.
  useEffect(
    () => () => {
      if (poll.current !== null) window.clearInterval(poll.current);
      popup.current?.close();
    },
    [],
  );

  useEffect(() => {
    let live = true;
    setError(null);
    void api.GET("/api/v1/me").then(({ data, error: failure }) => {
      if (!live) return;
      if (failure || !data) setError(envelope(failure));
      else updateLinked(data.paypal_linked);
    }).catch(() => { if (live) setError({ code: "REQUEST_FAILED", message: "Check your connection and try again." }); });
    return () => { live = false; };
  }, [attempt, updateLinked]);

  async function link() {
    setBusy("link"); setError(null);
    try {
      const { data, error: failure } = await api.GET("/api/v1/paypal/login/start");
      if (failure || !data) {
        setError(envelope(failure));
        setBusy(null);
        return;
      }
      const target = new URL(data.authorize_url);
      if (target.protocol !== "https:" || target.hostname !== "www.sandbox.paypal.com") {
        throw new Error("Invalid destination");
      }
      const handle = window.open(target.href, "fairpool-paypal-link", "width=520,height=720");
      if (!handle) {
        window.location.assign(target.href);
        return;
      }
      popup.current = handle;
      // The popup ends on the API callback; the opener is what notices the new link.
      const started = Date.now();
      stopPolling();
      poll.current = window.setInterval(() => {
        if (handle.closed) {
          stopPolling();
          popup.current = null;
          setBusy(null);
          setError({
            code: "REQUEST_FAILED",
            message: "The PayPal window closed before the link finished. Nothing was linked.",
          });
          return;
        }
        void api.GET("/api/v1/me").then(({ data: me }) => {
          if (me?.paypal_linked) {
            stopPolling();
            handle.close();
            updateLinked(true);
            setBusy(null);
          } else if (Date.now() - started > 120_000) {
            stopPolling();
            handle.close();
            setBusy(null);
            setError({
              code: "REQUEST_FAILED",
              message: "PayPal did not complete the connection. If PayPal itself says the redirect URL is invalid, this app's login callback is not registered for that address — see the README section on PayPal setup.",
            });
          }
        }).catch(() => undefined);
      }, 1500);
    } catch {
      setError({ code: "REQUEST_FAILED", message: "Check your connection and try again." });
      setBusy(null);
    }
  }

  async function unlink() {
    if (busy !== null) return;
    setBusy("unlink"); setError(null);
    try {
      const { error: failure } = await api.DELETE("/api/v1/paypal/link");
      if (failure) setError(envelope(failure));
      else { updateLinked(false); setConfirming(false); }
    } catch {
      setError({ code: "REQUEST_FAILED", message: "Check your connection and try again." });
    } finally { setBusy(null); }
  }

  return (
    <section aria-labelledby="paypal-settings-title" className="buyer-settings">
      <header className="settings-heading"><h1 id="paypal-settings-title" className="shop-title">PayPal settings</h1>
        <p className="shop-copy">Manage the account connection used for your pool entries. Linking places no charge or hold.</p></header>
      {error ? <Notice kind="error" code={error.code}>{error.message}</Notice> : null}
      <section className="settings-surface" aria-labelledby="paypal-connection-title">
        <div className="settings-connection"><span className="settings-service-icon"><Icon name="wallet" /></span><div><h2 id="paypal-connection-title">Your PayPal connection</h2>
          {linked === null ? error ? <p className="shop-copy">Your PayPal link could not be checked.</p> : <p role="status" className="shop-copy">Checking your PayPal link...</p>
            : <p className="settings-state" role="status"><Icon name={linked ? "check" : "info"} />{linked ? "A PayPal account is linked." : "No PayPal account is linked yet."}</p>}
        </div></div>
        <dl className="settings-facts"><div><dt>Pool participation</dt><dd>The connection helps FairPool limit one entry per linked PayPal account.</dd></div>
          <div><dt>Payment control</dt><dd>Linking grants no payment permission. Payments follow their own approval or recorded consent.</dd></div>
          <div><dt>Your password</dt><dd>Your PayPal password stays with PayPal.</dd></div></dl>
        {linked === null ? error ? <button type="button" className="button-secondary" onClick={() => setAttempt((value) => value + 1)}>Check again</button> : null
          : linked ? confirming ? <ConfirmAction returnFocusId="paypal-connection-action" title="Revoke this PayPal connection?" message="Your entries stay. Duplicate-account checks still apply at checkout, and some pools may require you to reconnect."
            confirmLabel="Confirm revoke link" cancelLabel="Keep linked" busy={busy !== null} onConfirm={() => void unlink()} onCancel={() => setConfirming(false)} />
            : <div className="settings-actions"><button type="button" className="button-secondary" id="paypal-connection-action" onClick={() => setConfirming(true)} disabled={busy !== null}>Revoke the link</button></div>
          : <div className="settings-actions"><button type="button" className="button-primary" id="paypal-connection-action" onClick={() => void link()} disabled={busy !== null}>{busy === "link" ? "Opening PayPal..." : "Link PayPal"}</button>
            <p className="shop-copy">Approve the connection in PayPal, then return here. Nothing is charged.</p></div>}
      </section>
      <p className="settings-footnote"><Icon name="shield" />A linked PayPal account helps limit duplicate entries; it does not prove one account per person.</p>
    </section>
  );
}

type Delegation = ApiComponents["schemas"]["DelegationView"];

// CR-14: the closed mandate vocabulary from ai-schemas.md section 9. The browser offers
// exactly these five predicates and three actions; the server refuses anything else.
type MandatePredicate = "PRICE_ABOVE" | "FUNDING_BELOW" | "BLOCKING_FLAG_ON_AWARD" | "DELIVERY_AFTER" | "NO_AWARD_BY";
type MandateAction = "PROCEED" | "REASK" | "HALT";
type MandateCondition = { predicate: MandatePredicate; action: MandateAction; params: Record<string, string> };
type MandateRequestCondition = { predicate: string; params: Record<string, string | number>; action: string };

const MANDATE_PREDICATES: MandatePredicate[] = ["PRICE_ABOVE", "FUNDING_BELOW", "BLOCKING_FLAG_ON_AWARD", "DELIVERY_AFTER", "NO_AWARD_BY"];
const MANDATE_ACTIONS: MandateAction[] = ["PROCEED", "REASK", "HALT"];
const PREDICATE_LABELS: Record<MandatePredicate, string> = {
  PRICE_ABOVE: "Price above a limit",
  FUNDING_BELOW: "Funding below a level",
  BLOCKING_FLAG_ON_AWARD: "An award carries a blocking flag",
  DELIVERY_AFTER: "Delivery after a date",
  NO_AWARD_BY: "No award by a date",
};
const ACTION_LABELS: Record<MandateAction, string> = { PROCEED: "Continue", REASK: "Ask me again", HALT: "Stop" };
const EMPTY_PARAMS: Record<MandatePredicate, Record<string, string>> = {
  PRICE_ABOVE: { amount: "" },
  FUNDING_BELOW: { percent: "60", hours_before_close: "24" },
  BLOCKING_FLAG_ON_AWARD: {},
  DELIVERY_AFTER: { date: "" },
  NO_AWARD_BY: { date: "" },
};
const DAY = /^\d{4}-\d{2}-\d{2}$/;
const AMOUNT = /^\d+(\.\d{1,2})?$/;

function actionWord(action: MandateAction): string {
  return action === "PROCEED" ? "continue" : action === "REASK" ? "ask me again" : "stop";
}

function describeCondition(condition: MandateCondition): string {
  const { params, action } = condition;
  switch (condition.predicate) {
    case "PRICE_ABOVE":
      return `- If the price is above USD ${params.amount || "(amount)"}, ${actionWord(action)}.`;
    case "FUNDING_BELOW":
      return `- If funding is below ${params.percent || "(percent)"}% ${params.hours_before_close || "(hours)"} hours before close, ${actionWord(action)}.`;
    case "BLOCKING_FLAG_ON_AWARD":
      return `- If an award carries a blocking flag, ${actionWord(action)}.`;
    case "DELIVERY_AFTER":
      return `- If delivery is after ${params.date || "(date)"}, ${actionWord(action)}.`;
    case "NO_AWARD_BY":
      return `- If no award is made by ${params.date || "(date)"}, ${actionWord(action)}.`;
  }
}

/** The buyer's readability view of the mandate; the hash covers the fields, not this text. */
function renderMandate(poolTitles: string[], cap: string, expires: string, conditions: MandateCondition[]): string {
  return [
    "FairPool agent mandate (version 1)",
    `Pools: ${poolTitles.length ? poolTitles.join(", ") : "no pools selected"}`,
    `Maximum per entry: USD ${cap.trim() || "(cap)"}`,
    `Expires: ${expires.trim() || "(expiry)"} (UTC)`,
    conditions.length ? `Conditions:\n${conditions.map(describeCondition).join("\n")}` : "Conditions: none",
    "This mandate approves no payment. You approve every charge yourself.",
  ].join("\n");
}

function serializeConditions(conditions: MandateCondition[]): MandateRequestCondition[] {
  return conditions.map((condition) => ({
    predicate: condition.predicate,
    action: condition.action,
    params: condition.predicate === "PRICE_ABOVE"
      ? { amount: condition.params.amount ?? "" }
      : condition.predicate === "FUNDING_BELOW"
        ? { percent: Number(condition.params.percent ?? ""), hours_before_close: Number(condition.params.hours_before_close ?? "") }
        : condition.predicate === "BLOCKING_FLAG_ON_AWARD"
          ? {}
          : { date: condition.params.date ?? "" },
  }));
}

function conditionProblem(condition: MandateCondition): boolean {
  const { predicate, params } = condition;
  if (predicate === "PRICE_ABOVE") return !AMOUNT.test(params.amount ?? "");
  if (predicate === "BLOCKING_FLAG_ON_AWARD") return false;
  if (predicate === "FUNDING_BELOW") {
    if (!/^\d+$/.test(params.percent ?? "") || !/^\d+$/.test(params.hours_before_close ?? "")) return true;
    const percent = Number(params.percent);
    const hours = Number(params.hours_before_close);
    return percent < 1 || percent > 100 || hours > 168;
  }
  return !DAY.test(params.date ?? "");
}

/** Canonical JSON: sorted keys and compact separators, the bytes the server also hashes. */
function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (value !== null && typeof value === "object") {
    const record = value as Record<string, unknown>;
    return `{${Object.keys(record).sort().map((key) => `${JSON.stringify(key)}:${canonicalJson(record[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

/** The mandate fields the server recomputes; the preview above is only a reading view. */
function canonicalMandate(poolIds: string[], capCents: number, expiresAt: string, conditions: MandateRequestCondition[], category: string | null = null): string {
  return canonicalJson({
    pool_ids: poolIds.map((id) => id.toLowerCase()).sort(),
    category,
    conditions,
    max_cap_cents: capCents,
    expires_at: expiresAt,
  });
}

/** SHA-256 of a UTF-8 string; Web Crypto, so it is the browser's own digest. */
async function sha256Hex(text: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

/** Buyer delegations: scoped, capped, expiring tokens shown exactly once. */
export function AgentSettingsPage({authorization}: {authorization?: Authorization} = {}) {
  const intentField = useRef<HTMLTextAreaElement>(null);
  const [scopeEdited, setScopeEdited] = useState(false);
  const [capEdited, setCapEdited] = useState(false);
  const [manualSetup, setManualSetup] = useState(false);
  const [fieldsOpen, setFieldsOpen] = useState(false);
  const [reviewReady, setReviewReady] = useState(false);
  const [urlCopied, setUrlCopied] = useState(false);
  const [matchedPools, setMatchedPools] = useState<ApiComponents["schemas"]["PoolSummary"][]>([]);
  const [connectionName, setConnectionName] = useState("");
  const [connecting, setConnecting] = useState(false);
  const [intent, setIntent] = useState("");
  const [proposalBusy, setProposalBusy] = useState(false);
  const [proposalNote, setProposalNote] = useState("");
  const [mandateCategory, setMandateCategory] = useState<string | null>(null);
  const [revoking, setRevoking] = useState<string | null>(null);
  const [revokeBusy, setRevokeBusy] = useState(false);
  const [tokenMessage, setTokenMessage] = useState("");
  const accessRead = useApiRead("/api/v1/me/delegations", (signal) => api.GET("/api/v1/me/delegations", {signal}), {enabled: !authorization});
  const poolsRead = useApiRead("/api/v1/pools?status=OPEN&limit=100", (signal) => api.GET("/api/v1/pools", {signal, params: {query: {status: "OPEN", limit: 100}}}), {staleTime: 60_000});
  const items: Delegation[] | null = accessRead.data?.items ?? null;
  const pools = useMemo(
    () => [...new Map([...(Array.isArray(poolsRead.data) ? poolsRead.data : []), ...matchedPools].map((pool) => [pool.pool_id, pool])).values()],
    [poolsRead.data, matchedPools],
  );
  const poolsProblem = poolsRead.error ? envelope(poolsRead.error) : null;
  const [selected, setSelected] = useState<string[]>([]);
  const [cap, setCap] = useState("600");
  const [expires, setExpires] = useState(() => new Date(Date.now() + 7 * 86400000).toISOString().slice(0, 16));
  const [conditions, setConditions] = useState<MandateCondition[]>([]);
  const [ratified, setRatified] = useState(false);
  const [token, setToken] = useState<string | null>(null);
  const [actionError, setError] = useState<{code: string; message: string} | null>(null);
  const error = actionError ?? (accessRead.error ? envelope(accessRead.error) : null);
  const [busy, setBusy] = useState(false);
  const poolsLoading = poolsRead.isPending;
  const renderedMandate = renderMandate(
    selected.map((id) => pools.find((pool) => pool.pool_id === id)?.title ?? id),
    cap,
    expires,
    conditions,
  ) + (mandateCategory ? `\nCategory: ${mandateCategory}` : "");
  useEffect(() => {
    if (manualSetup) intentField.current?.focus();
  }, [manualSetup]);
  // A refetch can drop a closed pool, and its id is part of the mandate hash: a
  // ratification given for the old set must not mint a token over the new one.
  useEffect(() => {
    setRatified(false);
  }, [renderedMandate]);
  useEffect(() => {
    if (pools.length === 0) return;
    const open = new Set(pools.map((pool) => pool.pool_id));
    setSelected((current) => {
      const next = current.filter((id) => open.has(id));
      return next.length === current.length ? current : next;
    });
  }, [pools]);
  async function load() {
    await Promise.all([accessRead.refetch({cancelRefetch: false}), poolsRead.refetch({cancelRefetch: false})]);
  }

  function addCondition() {
    if (conditions.length >= 5) return;
    setConditions((current) => [...current, { predicate: "PRICE_ABOVE", action: "REASK", params: { ...EMPTY_PARAMS.PRICE_ABOVE } }]);
    setRatified(false);
  }

  function updateCondition(index: number, change: (condition: MandateCondition) => MandateCondition) {
    setConditions((current) => current.map((condition, at) => (at === index ? change(condition) : condition)));
    // The buyer ratified the fields, not a form: any edit means ratifying again.
    setRatified(false);
  }

  function removeCondition(index: number) {
    setConditions((current) => current.filter((_, at) => at !== index));
    setRatified(false);
  }

  async function propose() {
    if (!intent.trim() || selected.length > 5) return;
    setProposalBusy(true); setProposalNote(""); setRatified(false);
    try {
      const {data, error: failure} = await api.POST("/api/v1/me/mandate-proposal", {
        body: {message: intent.trim(), pool_ids: scopeEdited ? selected : [], max_cap_cents: capEdited || fieldsOpen ? usdToCents(cap) : null},
      });
      if (failure || !data || data.source === "manual") {
        setProposalNote("Write or edit the mandate below. AI could not prepare a proposal.");
        setFieldsOpen(true); setReviewReady(true);
        return;
      }
      const missing = data.pool_ids.filter((id) => !pools.some((pool) => pool.pool_id === id));
      const details = await Promise.all(missing.map(async (pool_id) => {
        const result = await api.GET("/api/v1/pools/{pool_id}", {params: {path: {pool_id}}});
        if (!result.data || result.error) throw new Error("Pool unavailable");
        return result.data;
      }));
      setMatchedPools(details);
      setSelected(data.pool_ids);
      setFieldsOpen(data.max_cap_cents == null || data.expires_at == null); setReviewReady(true);
      setMandateCategory(data.category ?? null);
      setCap(data.max_cap_cents == null ? "" : `${Math.floor(data.max_cap_cents / 100)}.${String(data.max_cap_cents % 100).padStart(2, "0")}`);
      setExpires(data.expires_at ? new Date(data.expires_at).toISOString().slice(0, 16) : "");
      setConditions((data.conditions ?? []).map((condition) => ({
        predicate: condition.predicate as MandatePredicate, action: condition.action as MandateAction,
        params: Object.fromEntries(Object.entries((condition.params ?? {}) as Record<string, unknown>).map(([key, value]) => [key, String(value)])),
      })));
      setProposalNote(data.clarifying_question || "AI proposed the mandate below. Edit its fields, then review and ratify it.");
    } catch { setProposalNote("Write or edit the mandate below. AI is unavailable."); setFieldsOpen(true); setReviewReady(true); }
    finally { setProposalBusy(false); }
  }

  async function create(event: FormEvent) {
    event.preventDefault();
    const capCents = usdToCents(cap);
    const expiry = new Date(`${expires}Z`);
    if (!selected.length || capCents === null || !Number.isSafeInteger(capCents) || capCents <= 0 || Number.isNaN(expiry.getTime())) {
      setError({ code: "VALIDATION_ERROR", message: "Pick at least one pool, a positive cap and a future expiry." });
      return;
    }
    if (conditions.some(conditionProblem)) {
      setError({ code: "VALIDATION_ERROR", message: "Fill every condition with a valid amount, percentage, hours or date." });
      return;
    }
    if (!ratified) {
      setError({ code: "VALIDATION_ERROR", message: "Review the mandate and ratify the mandate before access is created." });
      return;
    }
    const expiresAt = expiry.toISOString();
    const conditionsPayload = serializeConditions(conditions);
    setBusy(true); setError(null); setToken(null);
    try {
      const body = {
        name: connectionName.trim() || null,
        scope: {
          pool_ids: selected, category: mandateCategory, mandate_version: "1",
          ratification_sha256: await sha256Hex(canonicalMandate(selected, capCents, expiresAt, conditionsPayload, mandateCategory)),
          conditions: conditionsPayload,
        }, max_cap_cents: capCents, expires_at: expiresAt,
      };
      if (authorization) { await decideAuthorization(authorization, body); return; }
      const { data, error: failure } = await api.POST("/api/v1/me/delegations", {body});
      if (failure || !data) setError(envelope(failure));
      else {
        setToken(data.token);
        setManualSetup(false); setReviewReady(false); setFieldsOpen(false);
        setSelected([]);
        setConditions([]);
        setRatified(false);
        await load();
      }
    } catch {
      setError({ code: "REQUEST_FAILED", message: "Check your connection and try again." });
    } finally { setBusy(false); }
  }

  async function revoke(id: string) {
    if (revokeBusy) return;
    setRevokeBusy(true); setError(null);
    try {
      const {error: failure} = await api.DELETE("/api/v1/me/delegations/{delegation_id}", {params: {path: {delegation_id: id}}});
      if (failure) setError(envelope(failure));
      else { setRevoking(null); await load(); }
    } catch { setError({code: "REQUEST_FAILED", message: "The delegation could not be revoked. Try again."}); }
    finally { setRevokeBusy(false); }
  }

  async function copyToken() {
    if (!token) return;
    try { await navigator.clipboard.writeText(token); setTokenMessage("Token copied. Store it securely."); }
    catch { setTokenMessage("Could not copy. Select the token and copy it manually."); }
  }

  return (
    <section aria-label={authorization ? "Agent mandate" : undefined} aria-labelledby={authorization ? undefined : "agent-settings-title"} className="buyer-settings agent-page">
      {!authorization ? <>
        <header className="agent-heading"><div><h1 id="agent-settings-title" className="shop-title">Agent connections</h1><p className="shop-copy">Let an agent find pools and manage entries. You approve every payment.</p></div><button type="button" className="button-primary" aria-expanded={connecting} onClick={() => setConnecting((value) => !value)}>Connect an agent<Icon name="arrow" /></button></header>
        {connecting ? <section className="settings-surface agent-connect-guide" aria-labelledby="connect-guide-title"><div className="agent-section-heading"><div><h2 id="connect-guide-title">Connect in your agent’s app</h2><p className="shop-copy">Add this server once. FairPool takes care of the secure connection.</p></div><button type="button" className="shop-quiet-button" onClick={() => setConnecting(false)}>Close guide</button></div>
          <label className="agent-url">MCP server URL<div><input className="form-input" readOnly value={`${API_BASE_URL}/mcp`} aria-label="MCP server URL" /><button type="button" className="button-secondary" onClick={() => void navigator.clipboard.writeText(`${API_BASE_URL}/mcp`).then(() => setUrlCopied(true)).catch(() => setUrlCopied(false))}><Icon name="copy" />{urlCopied ? "Copied" : "Copy URL"}</button></div></label>
          <ol className="agent-steps"><li><strong>Add the server</strong><span>Open your agent’s MCP or integrations settings and paste the URL.</span></li><li><strong>Choose Connect</strong><span>Your agent opens FairPool in your browser. No access token to copy.</span></li><li><strong>Review and approve</strong><span>Describe what you need. Check the proposed limits, then approve.</span></li></ol>
          <p className="agent-reassurance"><Icon name="shield" />Only connect a client you recognize. You can revoke it here at any time.</p>
        </section> : null}
        <div className="agent-connections-layout"><section className="settings-surface settings-delegations" aria-labelledby="connections-title"><div className="agent-section-heading"><h2 id="connections-title">Connections</h2>{items ? <span className="shop-copy">{items.length} connection{items.length === 1 ? "" : "s"}</span> : null}</div>
          {items === null ? error ? <button type="button" className="button-secondary" onClick={() => void load()}>Try again</button> : <p role="status" className="shop-copy">Loading connections…</p> : items.length === 0 ? <div className="agent-empty"><h3>No agents connected yet</h3><p className="shop-copy">Connect a compatible MCP client to get started. You choose what it can do before access is granted.</p><a href="#agent-help" className="signup-back">How access works</a></div> : <ul className="agent-connection-list">{items.map((item) => {
            const scope = item.scope as {pool_ids?: string[]};
            const state = item.revoked_at ? "Revoked" : Date.parse(item.expires_at) <= Date.now() ? "Expired" : "Active";
            return <li key={item.id} className="agent-connection"><div className="agent-connection-heading"><div><h3>{item.name || "Unnamed connection"}</h3><p className="shop-copy">Public prefix <code>{item.key_prefix || "Legacy connection"}</code></p></div><StatusPill status={state.toUpperCase()} tone={state === "Revoked" ? "bad" : state === "Active" ? "good" : "neutral"}>{state}</StatusPill></div>
              <p className="agent-connection-usage">Last used: {item.last_used_at ? formatDateTime(item.last_used_at) : "Never"}</p>
              <div className="agent-connection-footer"><details><summary>Access details</summary><p className="shop-copy">{scope.pool_ids?.length ?? 0} pool{scope.pool_ids?.length === 1 ? "" : "s"} · cap {formatCents(item.max_cap_cents)} · expires {formatDateTime(item.expires_at)}</p><ul className="delegation-pool-list" aria-label="Authorized pools">{(scope.pool_ids ?? []).map((id) => <li key={id}>{pools.find((pool) => pool.pool_id === id)?.title ?? "Previously selected pool"}</li>)}</ul></details>{!item.revoked_at ? <button type="button" className="shop-quiet-button" id={`agent-revoke-${item.id}`} onClick={() => setRevoking(item.id)}>Revoke</button> : null}</div>
              {revoking === item.id ? <ConfirmAction returnFocusId={`agent-revoke-${item.id}`} title="Revoke this connection?" message="The agent’s access stops immediately. Your existing pool entries are kept." confirmLabel="Confirm revoke delegation" cancelLabel="Keep delegation" busy={revokeBusy} onConfirm={() => void revoke(item.id)} onCancel={() => setRevoking(null)} /> : null}
            </li>;
          })}</ul>}
        </section><aside className="agent-control-note" id="agent-help"><h2>You stay in control</h2><dl><div><dt>Your pools</dt><dd>The agent can only act in the pools you approve.</dd></div><div><dt>Your limits</dt><dd>A per-entry cap and expiry bound its access.</dd></div><div><dt>Your payment</dt><dd>Every charge still needs human approval. No agent payment tool exists.</dd></div></dl><Link to="/my-pools" className="signup-back">See your pool entries<Icon name="arrow" /></Link></aside></div>
        {!manualSetup ? <div className="agent-manual-option"><div><h2>Client without OAuth?</h2><p className="shop-copy">The manual token fallback is available for clients that need it.</p></div><button type="button" className="button-secondary" onClick={() => setManualSetup(true)}>Set up manually</button></div> : null}
      </> : null}
      {error ? <Notice kind="error" code={error.code}>{error.message}</Notice> : null}
      {token ? <div className="settings-surface settings-token"><h2>Copy this token now. It is shown once.</h2><code className="mt-3 block break-all rounded-lg bg-canvas p-3 text-xs">{token}</code><p className="shop-copy">Store it in your client’s secure configuration. You can revoke access above.</p><div className="settings-actions"><button type="button" className="button-secondary" onClick={() => void copyToken()}><Icon name="copy" />Copy token</button><button type="button" className="shop-quiet-button" onClick={() => {setToken(null); setTokenMessage("");}}>Hide token</button></div>{tokenMessage ? <p role="status" className="shop-copy">{tokenMessage}</p> : null}</div> : null}
      {authorization || manualSetup ? <form onSubmit={(event) => void create(event)} className="settings-surface settings-delegation-form agent-editor">
        <div className="agent-section-heading"><div><h2>{authorization ? "What should your agent do?" : "Set up agent access"}</h2><p className="shop-copy">Describe the product, budget and time limit. We’ll find matching pools and prepare the details for you to review.</p></div>{!authorization ? <button type="button" className="shop-quiet-button" onClick={() => setManualSetup(false)}>Close setup</button> : null}</div>
        <label className="text-sm font-semibold">Describe your mandate<textarea ref={intentField} className="form-input mt-2 agent-intent" maxLength={2000} rows={3} value={intent} onChange={(event) => setIntent(event.target.value)} placeholder="Find a 4K monitor under $520 per entry, ask me above $500, and stop on 30 November 2026." /></label>
        <div className="agent-editor-actions"><button type="button" className="button-primary" disabled={proposalBusy || !intent.trim() || selected.length > 5} onClick={() => void propose()}>{proposalBusy ? "Finding pools and preparing…" : "Propose with AI"}<Icon name="arrow" /></button>{!fieldsOpen ? <button type="button" className="shop-quiet-button" onClick={() => {setFieldsOpen(true); setReviewReady(true);}}>Choose fields myself</button> : null}</div>
        {selected.length > 5 ? <p className="shop-copy">AI proposals support up to five selected pools.</p> : null}
        {proposalNote ? <p role="status" className="agent-proposal-note">{proposalNote}</p> : null}
        {fieldsOpen ? <div className="agent-fields"><div className="agent-section-heading"><h3 className="font-semibold">Edit access details</h3><button type="button" className="shop-quiet-button" onClick={() => setFieldsOpen(false)}>Done editing</button></div>
          {!authorization ? <label className="text-sm">Connection name<input className="form-input mt-1" maxLength={120} value={connectionName} onChange={(event) => setConnectionName(event.target.value)} placeholder="For example, my research assistant" /></label> : null}
        {mandateCategory ? <label className="text-sm">Category<input className="form-input mt-1" value={mandateCategory} onChange={(event) => {setMandateCategory(event.target.value || null); setRatified(false);}} /></label> : null}
        <fieldset>
          <legend className="text-sm font-semibold text-ink">Pools this delegation may use</legend>
          {poolsProblem ? (
            <div className="mt-2">
              <Notice kind="error" code={poolsProblem.code}>
                The open pools could not be loaded. {poolsProblem.message}{" "}
                <button
                  type="button"
                  className="signup-back inline-flex min-h-[44px] items-center"
                  onClick={() => void load().catch(() => setError({ code: "REQUEST_FAILED", message: "Check your connection and try again." }))}
                >
                  Reload pools
                </button>
              </Notice>
            </div>
          ) : poolsLoading ? <p role="status" className="shop-copy">Loading available pools...</p> : pools.length === 0 ? <p className="mt-2 text-sm text-muted">No open pools right now.</p> : (
            <div className="mt-2 grid gap-2">
              {pools.map((pool) => (
                <label key={pool.pool_id} className="settings-pool-option">
                  <input
                    type="checkbox"
                    checked={selected.includes(pool.pool_id)}
                    onChange={(event) => {
                      setScopeEdited(true);
                      setSelected((current) =>
                        event.target.checked ? [...current, pool.pool_id] : current.filter((id) => id !== pool.pool_id));
                      setRatified(false);
                    }}
                  />
                  {pool.title}
                </label>
              ))}
            </div>
          )}
        </fieldset>
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="text-sm">Maximum per entry (USD)
            <input className="form-input mt-1" inputMode="decimal" value={cap} onChange={(event) => { setCap(event.target.value); setCapEdited(true); setRatified(false); }} />
          </label>
          <label className="text-sm">Expires (UTC)
            <input className="form-input mt-1" type="datetime-local" value={expires} onChange={(event) => { setExpires(event.target.value); setRatified(false); }} />
          </label>
        </div>
        <fieldset>
          <legend className="text-sm font-semibold text-ink">Conditions this agent must honour</legend>
          <p className="shop-copy">Optional. These conditions guide your agent and are advisory in this build; FairPool enforces the pool scope, per-entry cap, expiry and revocation. The cap is not a total across pools.</p>
          <div className="mt-3 grid gap-3">
            {conditions.map((condition, index) => (
              <div key={index} className="grid gap-3 sm:grid-cols-2">
                <label className="text-sm">Condition {index + 1}
                  <select
                    className="form-input mt-1"
                    aria-label={`Condition ${index + 1} predicate`}
                    value={condition.predicate}
                    onChange={(event) => updateCondition(index, (current) => {
                      const predicate = event.target.value as MandatePredicate;
                      return { ...current, predicate, params: { ...EMPTY_PARAMS[predicate] } };
                    })}
                  >
                    {MANDATE_PREDICATES.map((predicate) => <option key={predicate} value={predicate}>{PREDICATE_LABELS[predicate]}</option>)}
                  </select>
                </label>
                {condition.predicate === "PRICE_ABOVE" ? (
                  <label className="text-sm">Amount (USD)
                    <input className="form-input mt-1" inputMode="decimal" aria-label={`Condition ${index + 1} amount (USD)`} value={condition.params.amount} onChange={(event) => updateCondition(index, (current) => ({ ...current, params: { ...current.params, amount: event.target.value } }))} />
                  </label>
                ) : condition.predicate === "FUNDING_BELOW" ? (
                  <>
                    <label className="text-sm">Percent of seats filled
                      <input className="form-input mt-1" inputMode="numeric" aria-label={`Condition ${index + 1} percent`} value={condition.params.percent} onChange={(event) => updateCondition(index, (current) => ({ ...current, params: { ...current.params, percent: event.target.value } }))} />
                    </label>
                    <label className="text-sm">Hours before close
                      <input className="form-input mt-1" inputMode="numeric" aria-label={`Condition ${index + 1} hours before close`} value={condition.params.hours_before_close} onChange={(event) => updateCondition(index, (current) => ({ ...current, params: { ...current.params, hours_before_close: event.target.value } }))} />
                    </label>
                  </>
                ) : condition.predicate === "BLOCKING_FLAG_ON_AWARD" ? null : (
                  <label className="text-sm">Date
                    <input className="form-input mt-1" type="date" aria-label={`Condition ${index + 1} date`} value={condition.params.date} onChange={(event) => updateCondition(index, (current) => ({ ...current, params: { ...current.params, date: event.target.value } }))} />
                  </label>
                )}
                <label className="text-sm">Then
                  <select className="form-input mt-1" aria-label={`Condition ${index + 1} action`} value={condition.action} onChange={(event) => updateCondition(index, (current) => ({ ...current, action: event.target.value as MandateAction }))}>
                    {MANDATE_ACTIONS.map((action) => <option key={action} value={action}>{ACTION_LABELS[action]}</option>)}
                  </select>
                </label>
                <button type="button" className="button-secondary w-fit" onClick={() => removeCondition(index)}>Remove condition {index + 1}</button>
              </div>
            ))}
          </div>
          <button type="button" className="button-secondary mt-3 w-fit" onClick={addCondition} disabled={conditions.length >= 5}>Add condition</button>
          {conditions.length >= 5 ? <p className="shop-copy">A mandate carries at most five conditions.</p> : null}
        </fieldset>
        </div> : null}
        {reviewReady ? <section className="agent-review" aria-labelledby="agent-review-title"><div className="agent-section-heading"><h3 id="agent-review-title">Review agent access</h3>{!fieldsOpen ? <button type="button" className="shop-quiet-button" onClick={() => setFieldsOpen(true)}>Edit limits and pools</button> : null}</div>
          <div data-testid="mandate-text" className="agent-mandate-text">{renderedMandate}</div>
          <p className="agent-reassurance"><Icon name="shield" />This mandate authorizes no payment. A human approves every charge.</p>
          {conditions.length ? <p className="shop-copy">Custom instructions are advisory. FairPool enforces your pool scope, per-entry cap, expiry and revocation.</p> : null}
          <details className="agent-technical"><summary>How this approval is recorded</summary><p className="shop-copy">FairPool stores a SHA-256 of the selected pools, cap, expiry and conditions. Editing any field means approving the mandate again.</p></details>
          <label className="settings-pool-option"><input type="checkbox" checked={ratified} onChange={(event) => setRatified(event.target.checked)} />I approve this mandate and will approve every payment myself.</label>
          <button type="submit" className="button-primary w-fit" disabled={busy || pools.length === 0}>{busy ? "Connecting…" : authorization ? "Approve connection" : "Create delegation"}</button>
        </section> : null}
      </form> : null}
    </section>
  );
}
