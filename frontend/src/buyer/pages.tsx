import { type FormEvent, lazy, Suspense, useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";

import {
  api,
  type ApiComponents,
  envelope,
  formatCents,
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
            placeholder="you@example.com"
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
  const [linked, setLinked] = useState<boolean | null>(null);
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
      else setLinked(data.paypal_linked);
    }).catch(() => { if (live) setError({ code: "REQUEST_FAILED", message: "Check your connection and try again." }); });
    return () => { live = false; };
  }, [attempt]);

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
            setLinked(true);
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
    if (!window.confirm("Revoke the PayPal link? Your entries stay; duplicate control falls back to checkout.")) return;
    setBusy("unlink"); setError(null);
    try {
      const { error: failure } = await api.DELETE("/api/v1/paypal/link");
      if (failure) setError(envelope(failure));
      else setLinked(false);
    } catch {
      setError({ code: "REQUEST_FAILED", message: "Check your connection and try again." });
    } finally { setBusy(null); }
  }

  return (
    <section aria-labelledby="paypal-settings-title" className="mx-auto w-full max-w-[760px]">
      <h1 id="paypal-settings-title" className="shop-title">PayPal settings</h1>
      <p className="shop-copy mt-2">
        Linking lets FairPool limit one entry per PayPal account. It places no charge and no hold,
        and it grants no payment permission.
      </p>
      {error ? <div className="mt-5"><Notice kind="error" code={error.code}>{error.message}</Notice></div> : null}
      <div className="panel mt-6 flex flex-col gap-4 p-6">
        {linked === null ? (
          error ? (
            <div className="flex flex-col items-start gap-3">
              <p className="text-sm text-muted">Your PayPal link could not be checked.</p>
              <button
                type="button"
                className="button-secondary min-h-[44px]"
                onClick={() => setAttempt((value) => value + 1)}
              >
                Check again
              </button>
            </div>
          ) : (
            <p role="status" className="text-sm text-muted">Checking your PayPal link…</p>
          )
        ) : (
          <>
            <p className="flex items-center gap-2 text-sm font-semibold text-ink">
              <Icon name={linked ? "check" : "wallet"} />
              {linked ? "A PayPal account is linked." : "No PayPal account is linked yet."}
            </p>
            {linked ? (
              <button type="button" className="button-secondary w-fit" onClick={() => void unlink()} disabled={busy !== null}>
                {busy === "unlink" ? "Revoking…" : "Revoke the link"}
              </button>
            ) : (
              <button type="button" className="button-primary w-fit" onClick={() => void link()} disabled={busy !== null}>
                {busy === "link" ? "Opening PayPal…" : "Link PayPal"}
              </button>
            )}
            <p className="text-xs text-muted">
              PayPal opens in a popup. Approve there and this page notices the link; nothing is charged.
            </p>
          </>
        )}
      </div>
    </section>
  );
}

type Delegation = ApiComponents["schemas"]["DelegationView"];

/** Buyer delegations: scoped, capped, expiring tokens shown exactly once. */
export function AgentSettingsPage() {
  const [items, setItems] = useState<Delegation[] | null>(null);
  const [pools, setPools] = useState<{ pool_id: string; title: string }[]>([]);
  const [poolsProblem, setPoolsProblem] = useState<{ code: string; message: string } | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [cap, setCap] = useState("600");
  const [expires, setExpires] = useState(() => new Date(Date.now() + 7 * 86400000).toISOString().slice(0, 16));
  const [token, setToken] = useState<string | null>(null);
  const [error, setError] = useState<{ code: string; message: string } | null>(null);
  const [busy, setBusy] = useState(false);

  async function load() {
    const [listedResult, poolsResult] = await Promise.allSettled([
      api.GET("/api/v1/me/delegations"),
      api.GET("/api/v1/pools", { params: { query: { status: "OPEN" } } }),
    ]);
    const listed = listedResult.status === "fulfilled" ? listedResult.value : null;
    const open = poolsResult.status === "fulfilled" ? poolsResult.value : null;
    if (!listed || listed.error || !listed.data) setError(envelope(listed?.error));
    else setItems(listed.data.items);
    if (!open || open.error || !Array.isArray(open.data)) {
      setPoolsProblem(envelope(open?.error));
    } else {
      setPools(open.data.map((pool) => ({ pool_id: pool.pool_id, title: pool.title })));
      setPoolsProblem(null);
    }
  }

  useEffect(() => {
    void load().catch(() => setError({ code: "REQUEST_FAILED", message: "Check your connection and try again." }));
  }, []);

  async function create(event: FormEvent) {
    event.preventDefault();
    const capCents = Math.round(Number(cap.replace(/,/g, "")) * 100);
    if (!selected.length || !Number.isFinite(capCents) || capCents <= 0 || new Date(expires) <= new Date()) {
      setError({ code: "VALIDATION_ERROR", message: "Pick at least one pool, a positive cap and a future expiry." });
      return;
    }
    setBusy(true); setError(null); setToken(null);
    try {
      const { data, error: failure } = await api.POST("/api/v1/me/delegations", {
        body: {
          scope: { pool_ids: selected, category: null },
          max_cap_cents: capCents,
          expires_at: new Date(expires).toISOString(),
        },
      });
      if (failure || !data) setError(envelope(failure));
      else { setToken(data.token); setSelected([]); await load(); }
    } catch {
      setError({ code: "REQUEST_FAILED", message: "Check your connection and try again." });
    } finally { setBusy(false); }
  }

  async function revoke(id: string) {
    if (!window.confirm("Revoke this delegation? Any AI client holding its token stops working immediately.")) return;
    const { error: failure } = await api.DELETE("/api/v1/me/delegations/{delegation_id}", {
      params: { path: { delegation_id: id } },
    });
    if (failure) setError(envelope(failure)); else await load();
  }

  return (
    <section aria-labelledby="agent-settings-title" className="mx-auto w-full max-w-[820px]">
      <h1 id="agent-settings-title" className="shop-title">Agent settings</h1>
      <p className="shop-copy mt-2">
        A delegation lets your AI client join, list and withdraw entries inside the pools you choose,
        up to the cap you set. It cannot pay: only you approve payments on PayPal.
      </p>
      {error ? <div className="mt-5"><Notice kind="error" code={error.code}>{error.message}</Notice></div> : null}
      {token ? (
        <div className="panel mt-5 p-5">
          <p className="text-sm font-semibold text-ink">Copy this token now. It is shown once.</p>
          <code className="mt-2 block break-all rounded-lg bg-canvas p-3 text-xs">{token}</code>
          <p className="mt-2 text-xs text-muted">FairPool stores only an HMAC of this token; it cannot be shown again.</p>
        </div>
      ) : null}
      <form onSubmit={(event) => void create(event)} className="panel mt-6 flex flex-col gap-4 p-6">
        <fieldset>
          <legend className="text-sm font-semibold text-ink">Pools this delegation may use</legend>
          {poolsProblem ? (
            <div className="mt-2">
              <Notice kind="error" code={poolsProblem.code}>
                The open pools could not be loaded. {poolsProblem.message}{" "}
                <button
                  type="button"
                  className="signup-back inline-flex min-h-[44px] items-center"
                  onClick={() => void load().catch(() => setPoolsProblem({ code: "REQUEST_FAILED", message: "Check your connection and try again." }))}
                >
                  Reload pools
                </button>
              </Notice>
            </div>
          ) : pools.length === 0 ? <p className="mt-2 text-sm text-muted">No open pools right now.</p> : (
            <div className="mt-2 grid gap-2">
              {pools.map((pool) => (
                <label key={pool.pool_id} className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={selected.includes(pool.pool_id)}
                    onChange={(event) => setSelected((current) =>
                      event.target.checked ? [...current, pool.pool_id] : current.filter((id) => id !== pool.pool_id))}
                  />
                  {pool.title}
                </label>
              ))}
            </div>
          )}
        </fieldset>
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="text-sm">Maximum total per entry (USD)
            <input className="form-input mt-1" inputMode="decimal" value={cap} onChange={(event) => setCap(event.target.value)} />
          </label>
          <label className="text-sm">Expires
            <input className="form-input mt-1" type="datetime-local" value={expires} onChange={(event) => setExpires(event.target.value)} />
          </label>
        </div>
        <button type="submit" className="button-primary w-fit" disabled={busy || pools.length === 0}>
          {busy ? "Creating…" : "Create delegation"}
        </button>
      </form>
      <div className="panel mt-6 p-6">
        <h2 className="text-base font-semibold text-ink">Your delegations</h2>
        {items === null ? <p role="status" className="mt-3 text-sm text-muted">Loading delegations…</p> : items.length === 0 ? (
          <p className="mt-3 text-sm text-muted">No delegations yet. An AI client needs one before it can act for you.</p>
        ) : (
          <ul className="mt-3 grid gap-3">
            {items.map((item) => {
              const scope = item.scope as { pool_ids?: string[] };
              return (
                <li key={item.id} className="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-3 text-sm">
                  <span>
                    {scope.pool_ids?.length ?? 0} pool{scope.pool_ids?.length === 1 ? "" : "s"} · cap {formatCents(item.max_cap_cents)} · expires {new Date(item.expires_at).toLocaleString()}
                    {item.revoked_at ? " · revoked" : ""}
                  </span>
                  {item.revoked_at ? null : (
                    <button type="button" className="button-secondary" onClick={() => void revoke(item.id)}>Revoke</button>
                  )}
                </li>
              );
            })}
          </ul>
        )}
        <p className="mt-4 text-xs text-muted">
          Agent API: <a className="underline" href="/openapi.json">the OpenAPI document</a>. The MCP endpoint offers
          exactly four tools (list_pools, enter_pool, list_entries, withdraw_entry) and no payment tool. A stdlib-only
          sample client lives at samples/agent_client.py in the repository.
        </p>
      </div>
    </section>
  );
}
