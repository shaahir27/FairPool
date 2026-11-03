import { type FormEvent, useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";

import { api, type ApiComponents, type DeliveryAddress, DeliveryAddressFields, EMPTY_DELIVERY_ADDRESS, Icon, Notice, resetSessionCache, setCsrfToken } from "../shared";
import { AuthFrame } from "./AuthFrame";

type SignupState = "loading" | "not_started" | "pending" | "ready" | "expired" | "registered" | "unreachable";
type Failure = { code: string; message: string };

const DRAFT_KEY = "fairpool_signup_draft";

type SignupDraft = {
  email: string;
  name: string;
  address: DeliveryAddress;
};

function readDraft(): SignupDraft | null {
  try {
    const raw = sessionStorage.getItem(DRAFT_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (typeof parsed === "object" && parsed !== null) {
      return {
        email: typeof parsed.email === "string" ? parsed.email : "",
        name: typeof parsed.name === "string" ? parsed.name : "",
        address: typeof parsed.address === "object" && parsed.address !== null
          ? { ...EMPTY_DELIVERY_ADDRESS, ...parsed.address }
          : EMPTY_DELIVERY_ADDRESS,
      };
    }
  } catch {
    // Ignore storage parse errors
  }
  return null;
}

function writeDraft(draft: SignupDraft): void {
  try {
    // Non-password fields only. Passwords are NEVER persisted in drafts or browser storage.
    sessionStorage.setItem(DRAFT_KEY, JSON.stringify(draft));
  } catch {
    // Ignore storage write errors
  }
}

function clearDraft(): void {
  try {
    sessionStorage.removeItem(DRAFT_KEY);
  } catch {
    // Ignore
  }
}

function useSignup() {
  const [state, setState] = useState<SignupState>("loading");
  const [enabled, setEnabled] = useState(false);
  const [prefill, setPrefill] = useState<ApiComponents["schemas"]["SignupPrefill"] | null>(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let live = true;
    void api.GET("/api/v1/auth/paypal/status").then(({ data, error }) => {
      if (!live) return;
      if (error || !data) { setState("unreachable"); return; }
      setEnabled(data.enabled);
      setPrefill(data.prefill ?? null);
      setState(data.status);
    }).catch(() => { if (live) setState("unreachable"); });
    return () => { live = false; };
  }, [attempt]);
  return { state, enabled, prefill, retry: () => { setState("loading"); setAttempt((v) => v + 1); } };
}

function Steps({ current }: { current: 1 | 2 }) {
  return <ol className="signup-steps" aria-label="Account setup progress">
    <li aria-current={current === 1 ? "step" : undefined} className={current === 1 ? "is-current" : "is-done"}>
      <span>{current === 2 ? <Icon name="check" /> : "1"}</span> Connect PayPal
    </li>
    <li aria-current={current === 2 ? "step" : undefined} className={current === 2 ? "is-current" : ""}>
      <span>2</span> Your account
    </li>
  </ol>;
}

function Recovery({ retry }: { retry: () => void }) {
  return <div className="signup-recovery">
    <Notice kind="error" code="REQUEST_FAILED">We couldn’t check your connection. Try again to continue.</Notice>
    <button className="button-secondary w-full" type="button" onClick={retry}>Try again</button>
  </div>;
}

function Loading() {
  return <p className="signup-loading" role="status"><span className="signup-spinner" aria-hidden="true" />Checking your PayPal connection…</p>;
}

export function RegisterPage() {
  const { state, enabled, retry } = useSignup();
  const location = useLocation();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Failure | null>(null);
  const reason = new URLSearchParams(location.search).get("reason");
  const reasons: Record<string, string> = {
    cancelled: "The PayPal connection wasn’t completed. You can try again when you’re ready.",
    expired: "Your connection expired. Connect PayPal again to keep your account secure.",
    unavailable: "PayPal couldn’t finish the connection. Please try again.",
    account_exists: "This PayPal account already belongs to a FairPool account. Sign in to that account to continue.",
    refresh: "You can connect PayPal again to refresh your details or use a different account.",
  };

  async function connect() {
    if (busy) return;
    setBusy(true); setError(null);
    try {
      const { data, error: failure } = await api.POST("/api/v1/auth/paypal/start");
      if (failure || !data) {
        setError({ code: "CONNECTION_FAILED", message: "We couldn’t start the PayPal connection. Please try again." });
        setBusy(false); return;
      }
      const target = new URL(data.authorize_url);
      if (target.protocol !== "https:" || target.hostname !== "www.sandbox.paypal.com") throw new Error("Invalid destination");
      window.location.assign(target.href);
    } catch {
      setError({ code: "REQUEST_FAILED", message: "Check your connection and try again." });
      setBusy(false);
    }
  }
  return <AuthFrame headline="One account. A place in the pool." valueLine="Connect with PayPal, make yourself at home, and join the group on your terms.">
    <div className="signup-flow">
      <Steps current={1} />
      <h1 className="auth-title">Your fair start.</h1>
      <p className="signup-lead">First, connect PayPal. Then create the FairPool sign-in you’ll use every day.</p>
      {error ? <Notice kind="error" code={error.code}>{error.message}</Notice> : reason && reasons[reason] ? <Notice kind="warn">{reasons[reason]}</Notice> : null}
      <div className="signup-connection">
        <Icon name="shield" />
        <div><strong>A connected account, a clearer start.</strong><p>Connecting PayPal helps us limit duplicate entries from the same linked account.</p></div>
      </div>
      {state === "loading" ? <Loading /> : state === "unreachable" ? <Recovery retry={retry} /> : <>
        {!enabled ? <Notice kind="warn">PayPal signup is temporarily unavailable. Existing members can still sign in.</Notice> : null}
        {state === "registered" ? (
          <div className="flex flex-col gap-2">
            <Notice kind="info">This PayPal connection already belongs to a FairPool account. Sign in to continue.</Notice>
            <Link className="button-primary w-full text-center" to="/login">Sign in <Icon name="arrow" /></Link>
          </div>
        ) : state === "ready" && !reason ? (
          <div className="flex flex-col gap-2">
            <Link className="button-primary w-full text-center" to="/register/details">
              Continue setup with connected PayPal <Icon name="arrow" />
            </Link>
            <button
              className="button-secondary w-full"
              type="button"
              disabled={!enabled || busy}
              onClick={() => void connect()}
            >
              {busy ? "Opening PayPal…" : "Connect a different PayPal account"}
            </button>
          </div>
        ) : (
          <button className="button-primary signup-connect w-full" type="button" disabled={!enabled || busy} onClick={() => void connect()}>
            {busy ? "Opening PayPal…" : "Continue with PayPal"}<Icon name="arrow" />
          </button>
        )}
      </>}
      <p className="signup-assurance"><Icon name="lock" />No charge. No hold. You’ll return here after PayPal.</p>
      <p className="auth-switch">Already a member? <Link to="/login">Sign in</Link></p>
    </div>
  </AuthFrame>;
}

export function SignupConnectedPage() {
  const { state, retry } = useSignup();
  const navigate = useNavigate();
  useEffect(() => {
    if (state === "registered") navigate("/login", { replace: true });
    if (["not_started", "expired", "pending"].includes(state)) navigate("/register?reason=expired", { replace: true });
    if (state !== "ready") return;
    const timer = window.setTimeout(() => navigate("/register/details", { replace: true }), 2000);
    return () => window.clearTimeout(timer);
  }, [state, navigate]);
  return <AuthFrame headline="A good beginning, together." valueLine="Your account connection is the first step. Your FairPool account is next.">
    <div className="signup-flow signup-connected">
      {state === "ready" ? <>
        <div className="signup-success-mark" aria-hidden="true"><Icon name="check" /></div>
        <h1 className="auth-title" tabIndex={-1}>You’re connected.</h1>
        <p className="signup-lead">PayPal has confirmed your account connection. Let’s make your FairPool account yours.</p>
        <p className="signup-next" role="status">Taking you to account setup…</p>
        <Link className="button-primary w-full" to="/register/details" replace>Continue now <Icon name="arrow" /></Link>
        <p className="signup-assurance">No payment has been requested.</p>
      </> : state === "unreachable" ? <Recovery retry={retry} /> : <Loading />}
    </div>
  </AuthFrame>;
}

export function SignupDetailsPage() {
  const { state, prefill, retry } = useSignup();
  const navigate = useNavigate();
  const heading = useRef<HTMLHeadingElement>(null);
  const hydrated = useRef(false);
  const [stage, setStage] = useState<"account" | "delivery">("account");
  const [address, setAddress] = useState<DeliveryAddress>(EMPTY_DELIVERY_ADDRESS);
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Failure | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const mismatch = confirmation.length > 0 && password !== confirmation;

  useEffect(() => {
    if (state === "registered") { navigate("/login", { replace: true }); return; }
    if (["not_started", "expired", "pending"].includes(state)) navigate("/register?reason=expired", { replace: true });
    if (state === "ready") heading.current?.focus();
    if (state === "ready" && !hydrated.current) {
      hydrated.current = true;
      const draft = readDraft();
      if (draft && (draft.email || draft.name || draft.address.line1)) {
        setEmail(draft.email);
        setName(draft.name);
        setAddress(draft.address);
      } else {
        const initialEmail = prefill?.email ?? "";
        const initialName = prefill?.display_name ?? "";
        const initialAddr = {
          ...EMPTY_DELIVERY_ADDRESS,
          ...prefill?.address,
          name: prefill?.display_name ?? "",
        };
        setEmail(initialEmail);
        setName(initialName);
        setAddress(initialAddr);
        writeDraft({ email: initialEmail, name: initialName, address: initialAddr });
      }
    }
  }, [state, prefill, navigate, stage]);

  function handleNameChange(val: string) {
    setName(val);
    writeDraft({ email, name: val, address });
  }

  function handleEmailChange(val: string) {
    setEmail(val);
    writeDraft({ email: val, name: name, address });
  }

  function handleAddressChange(next: DeliveryAddress) {
    setAddress(next);
    writeDraft({ email, name, address: next });
  }

  function handleStartOver() {
    clearDraft();
    navigate("/register?reason=refresh", { replace: true });
  }

  async function submit(event: FormEvent) {
    event.preventDefault(); setSubmitted(true);
    if (busy || password !== confirmation) return;
    if (stage === "account") {
      const nextAddr = { ...address, name: address.name || name };
      setAddress(nextAddr);
      writeDraft({ email, name, address: nextAddr });
      setSubmitted(false); setStage("delivery"); return;
    }
    setBusy(true); setError(null);
    try {
      const { data, error: failure } = await api.POST("/api/v1/auth/register", {
        body: { email, display_name: name, password, password_confirm: confirmation, delivery_address: address },
      });
      if (failure || !data) {
        const code = (failure as { error?: { code?: string } } | undefined)?.error?.code;
        if (code === "FORBIDDEN" || code === "PAYPAL_LINK_CONFLICT") {
          navigate(`/register?reason=${code === "PAYPAL_LINK_CONFLICT" ? "account_exists" : "expired"}`, { replace: true }); return;
        }
        setError({ code: code ?? "VALIDATION_ERROR", message: "We couldn’t create your account. Check your details, or sign in if you already have an account." }); return;
      }
      setCsrfToken(data.csrf_token); resetSessionCache();
      clearDraft();
      navigate("/discover", { replace: true });
    } catch { setError({ code: "REQUEST_FAILED", message: "Check your connection and try again. Your details are still here." }); }
    finally { setBusy(false); }
  }

  return <AuthFrame headline="A little about you. A lot to look forward to." valueLine="Choose your FairPool sign-in. Your PayPal account connection stays with your account.">
    <div className="signup-flow">
      {state === "unreachable" ? <Recovery retry={retry} /> : state !== "ready" ? <Loading /> : <>
        <Steps current={2} />
        <h1 ref={heading} tabIndex={-1} className="auth-title">{stage === "account" ? "Make it yours." : "Where should it arrive?"}</h1>
        <p className="signup-lead">{stage === "account" ? "Check your details and choose your FairPool password. You can edit anything PayPal shared." : "Check your delivery address. We’ll save it for faster checkout, and you can change it or add another later."}</p>
        <div className="signup-linked">
          <Icon name="check" />PayPal connected
          <button type="button" className="signup-back text-xs ml-auto" onClick={handleStartOver} disabled={busy}>
            Use different PayPal account
          </button>
          <span>No payment permission granted</span>
        </div>
        {!prefill && stage === "account" ? (
          <p className="signup-help">
            You can enter your details here, or{" "}
            <button type="button" className="underline text-accent cursor-pointer" onClick={handleStartOver}>
              connect PayPal again to import them
            </button>.
          </p>
        ) : null}
        {error ? <Notice kind="error" code={error.code}>{error.message}</Notice> : null}
        <form className="auth-fields signup-details" onSubmit={(event) => void submit(event)}>
          {stage === "account" ? <>
          <label><span id="signup-name-label">Display name</span><input aria-labelledby="signup-name-label" className="form-input" autoComplete="nickname" required maxLength={120} value={name} onChange={(e) => handleNameChange(e.target.value)} /><span className="signup-help">How your name appears in FairPool.</span></label>
          <label><span id="signup-email-label">Email</span><input aria-labelledby="signup-email-label" className="form-input" type="email" autoComplete="email" required maxLength={320} value={email} onChange={(e) => handleEmailChange(e.target.value)} /><span className="signup-help">Your email for FairPool sign-in.</span></label>
          <label><span id="signup-password-label">Password</span><span className="password-field"><input className="form-input" type={show ? "text" : "password"} autoComplete="new-password" minLength={8} maxLength={200} required aria-labelledby="signup-password-label" aria-describedby="signup-password-help" value={password} onChange={(e) => setPassword(e.target.value)} /><button className="password-toggle" type="button" aria-label={show ? "Hide password" : "Show password"} aria-pressed={show} onClick={() => setShow((v) => !v)}><Icon name="eye" /></button></span><span id="signup-password-help" className="signup-help">At least 8 characters. A longer passphrase works well.</span></label>
          <label><span id="signup-confirm-label">Repeat password</span><input className="form-input" type={show ? "text" : "password"} autoComplete="new-password" minLength={8} maxLength={200} required aria-labelledby="signup-confirm-label" value={confirmation} aria-invalid={mismatch || (submitted && !confirmation)} aria-describedby={mismatch ? "signup-password-error" : undefined} onChange={(e) => setConfirmation(e.target.value)} />{mismatch ? <span id="signup-password-error" className="signup-field-error">Your passwords don’t match yet.</span> : null}</label>
          </> : <DeliveryAddressFields value={address} onChange={handleAddressChange} prefix="signup-delivery" />}
          {stage === "delivery" ? (
            <button className="signup-back" type="button" onClick={() => setStage("account")} disabled={busy}>
              Back to account details
            </button>
          ) : (
            <button className="signup-back" type="button" onClick={handleStartOver} disabled={busy}>
              ← Connect a different PayPal account
            </button>
          )}
          <button className="button-primary w-full" type="submit" disabled={busy || mismatch}>{busy ? "Creating your account…" : stage === "account" ? "Continue to delivery" : "Create account"}<Icon name="arrow" /></button>
        </form>
        <p className="auth-switch">Already have an account? <Link to="/login">Sign in</Link></p>
      </>}
    </div>
  </AuthFrame>;
}
