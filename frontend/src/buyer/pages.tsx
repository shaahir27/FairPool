import { type FormEvent, lazy, Suspense, useEffect, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";

import {
  api,
  Icon,
  Notice,
  PlaceholderPage,
  resetSessionCache,
  setCsrfToken,
} from "../shared";
const OrderStatusCard = lazy(() => import("../checkout").then((module) => ({ default: module.OrderStatusCard })));

import { AuthFrame } from "./AuthFrame";
import { resetBuyerPrefetch } from "./prefetch";
export { MyPoolsPage } from "./my-pools/MyPoolsPage";
export { OrdersPage } from "./orders/OrdersPage";
export { RegisterPage } from "./signup";

function envelope(failure: unknown): { code: string; message: string } {
  const value = failure as { error?: { code?: string; message?: string } } | undefined;
  return {
    code: value?.error?.code ?? "REQUEST_FAILED",
    message: value?.error?.message ?? "The request could not be completed.",
  };
}

export function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const merchant = new URLSearchParams(location.search).get("role") === "merchant";
  const from = (location.state as { from?: string } | null)?.from ?? (merchant ? "/merchant/demand" : "/discover");
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
      navigate(from, { replace: true });
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

export function PayPalSettingsPage() {
  return (
    <PlaceholderPage
      title="PayPal settings"
      route="/settings/paypal"
      task="T06B04"
      taskTitle="PayPal Login link and routing"
      planned={[
        "Whether a PayPal account is linked.",
        "Start the link and revoke it while no active entry uses it.",
        "The disclosure that linking places no charge and no hold.",
      ]}
    />
  );
}

export function AgentSettingsPage() {
  return (
    <PlaceholderPage
      title="Agent settings"
      route="/settings/agents"
      task="T07B04"
      taskTitle="Agent API delegations and docs"
      planned={[
        "Create, list and revoke buyer delegations with a cap and an expiry.",
        "The one-time token display.",
        "Agent docs: the API reference and a sample script that cannot pay.",
      ]}
    />
  );
}
