import { type FormEvent, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";

import {
  api,
  Icon,
  Notice,
  PlaceholderPage,
  resetSessionCache,
  setCsrfToken,
} from "../shared";
import { OrderStatusCard } from "../checkout";

import { AuthFrame } from "./AuthFrame";
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
  const from = (location.state as { from?: string } | null)?.from ?? "/";
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ code: string; message: string } | null>(null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { data, error: failure } = await api.POST("/api/v1/auth/login", { body: { email, password } });
      if (failure || !data) { setError(envelope(failure)); return; }
      setCsrfToken(data.csrf_token);
      resetSessionCache();
      navigate(from, { replace: true });
    } catch {
      setError({ code: "REQUEST_FAILED", message: "Check your connection and try again." });
    } finally { setBusy(false); }
  };

  return (
    <AuthFrame
      headline="Join together. Let merchants compete for your group."
      valueLine="Join a pool for free. Merchants bid in a sealed auction, and you approve your own payment."
    >
      <h1 className="auth-title">Sign in</h1>
      <p className="mt-2 text-sm text-muted">Welcome back. Pick up where your pools left off.</p>
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
      <p className="auth-switch">
        New to FairPool?{" "}
        <Link className="font-semibold underline decoration-accent decoration-2 underline-offset-4" to="/register">
          Create account
        </Link>
      </p>
    </AuthFrame>
  );
}

export function BuyerOrderPage() {
  const { buyerOrderId } = useParams<{ buyerOrderId: string }>();
  if (!buyerOrderId) {
    return <p className="p-6 text-sm text-muted">This order link is incomplete.</p>;
  }
  return <OrderStatusCard buyerOrderId={buyerOrderId} />;
}

export function DiscoverPage() {
  return (
    <PlaceholderPage
      title="Discover and Join"
      route="/"
      task="T06B05"
      taskTitle="Buyer UI v1: Discover and Join"
      planned={[
        "The prompt bar and the manual request form for intake.",
        "Open pools with their public entry counts.",
        "The confirmation card, the join action and the entry receipt.",
      ]}
    />
  );
}

export function MyPoolsPage() {
  return (
    <PlaceholderPage
      title="My Pools"
      route="/my-pools"
      task="T07B01"
      taskTitle="Buyer UI v2: My Pools and Orders"
      planned={[
        "Pending entries for open, closed and bidding pools.",
        "Waitlist positions reported by the allocation.",
        "Action-required entries with the offer countdown and checkout hand-off.",
      ]}
    />
  );
}

export function OrdersPage() {
  return (
    <PlaceholderPage
      title="Orders"
      route="/orders"
      task="T07B01"
      taskTitle="Buyer UI v2: My Pools and Orders"
      planned={[
        "Orders grouped by outcome: funded, voided, refunded.",
        "Each row with its amount and winning merchant.",
        "Status history and the PayPal capture reference.",
      ]}
    />
  );
}

export function PoolPage() {
  return (
    <PlaceholderPage
      title="Pool detail"
      route="/pools/:poolId"
      task="T06B05"
      taskTitle="Buyer UI v1: Discover and Join"
      planned={[
        "Lot plan, timeline and the live entry count.",
        "The rules link and rules_hash.",
        "The join action and the buyer's entry status.",
      ]}
    />
  );
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
