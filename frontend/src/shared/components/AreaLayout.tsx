import { useState } from "react";
import { Suspense, type ReactNode } from "react";
import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";
import { Brand } from "./Brand";
import { HonestyLabels } from "./HonestyLabels";
import { Icon } from "./Icon";
import { api } from "../api/client";
import { setCsrfToken } from "../lib/csrf";
import { accountState, resetSessionCache } from "../lib/session";
import "../commerce.css";

export type AreaTab = { to: string; label: string; end: boolean };
export type AreaUtilityLink = { to: string; label: string };
type AreaLayoutProps = { workspace: string; tabs: readonly AreaTab[]; utilityLinks?: readonly AreaUtilityLink[]; children?: ReactNode };

function WorkspaceContent({ children }: { children?: ReactNode }) {
  return <Suspense fallback={<div className="workspace-loading" role="status" aria-label="Loading workspace page"><p>Loading your page…</p><div className="skeleton" /></div>}>
    {children ?? <Outlet />}
  </Suspense>;
}

/**
 * Sign out of the workspace.
 *
 * The server ends the session and clears the cookie; the browser then has to forget the
 * CSRF token and stop treating its cached answer as "signed in", or the next route would
 * render while every call fails. A refused call says so rather than pretending: the
 * buyer is still signed in, and saying otherwise would be a lie about a money surface.
 */
function SignOut({ className = "account-nav-link" }: { className?: string }) {
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  const signOut = async () => {
    if (busy) return;
    setBusy(true);
    setFailed(false);
    try {
      const { error } = await api.POST("/api/v1/auth/logout");
      if (error) {
        setFailed(true);
        return;
      }
      setCsrfToken(null);
      resetSessionCache("out");
      navigate("/login", { replace: true });
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <button type="button" className={className} disabled={busy} onClick={() => void signOut()}>
        <Icon name="arrow" />
        <span>{busy ? "Signing out…" : "Sign out"}</span>
      </button>
      {failed ? (
        <p className="basis-full text-xs leading-relaxed" role="alert">
          Still signed in — the server did not answer. Try again.
        </p>
      ) : null}
    </>
  );
}

export function AreaLayout({ workspace, tabs, utilityLinks = [], children }: AreaLayoutProps) {
  if (workspace === "Buyer workspace") {
    const account = accountState();
    const firstName = account ? account.display_name.split(" ")[0] : null;
    const links = tabs.map((tab, index) => (
      <NavLink key={tab.to} to={tab.to} end={tab.end} className={({ isActive }) => `account-nav-link ${isActive ? "is-active" : ""}`}>
        <Icon name={index === 0 ? "search" : index === 1 ? "layers" : "bag"} />
        <span>{tab.label}</span><Icon name="chevron" className="nav-chevron" />
      </NavLink>
    ));
    return <>
      <div className="commerce-shell">
        <a href="#main" className="skip-link">Skip to content</a>
        <aside className="account-sidebar">
          <Link to="/" aria-label="FairPool home"><Brand /></Link>
          {account ? (
            <div className="sidebar-hello">
              <p className="sidebar-hello-name font-display">Hi{firstName ? `, ${firstName}` : ""}</p>
              {/* The link state is the server's own answer, and no more is claimed:
                  linking is what lets a pool hold one entry per PayPal account. */}
              <p className="sidebar-hello-state">
                <Icon name="wallet" />
                {account.paypal_linked ? "PayPal account linked" : "No PayPal account linked yet"}
              </p>
            </div>
          ) : (
            <p className="sidebar-caption">Your shopping space</p>
          )}
          <nav aria-label={`${workspace} tabs`} className="account-navigation">{links}</nav>
          <div className="sidebar-bottom">
            <nav aria-label={`${workspace} settings`} className="account-navigation secondary-navigation">
              {utilityLinks.map((link) => <NavLink key={link.to} to={link.to} className="account-nav-link"><Icon name={link.to.includes("paypal") ? "wallet" : "settings"} /><span>{link.label}</span></NavLink>)}
            </nav>
            <div className="sidebar-note"><Icon name="layers" /><strong>A better price, together.</strong><p>One pool. A shared opportunity. Your own order.</p></div>
            <p className="sidebar-demo">PayPal Sandbox demo<br />No real money moves.</p>
            <SignOut />
          </div>
        </aside>
        <div className="commerce-workspace">
          <header className="account-topbar">
            <div className="account-mobile-brand"><Link to="/" aria-label="FairPool home"><Brand /></Link></div>
            <span className="account-context">{account ? `${account.display_name}'s account` : "Your account"}</span>
            <div className="account-topbar-right"><HonestyLabels kinds={["sandbox"]} />
              <details className="account-mobile-menu" onClick={(event) => { if ((event.target as Element).closest("a")) event.currentTarget.open = false; }} onKeyDown={(event) => { if (event.key === "Escape") { event.currentTarget.open = false; event.currentTarget.querySelector("summary")?.focus(); } }}><summary><Icon name="menu" /><span className="sr-only">Open account navigation</span></summary><nav aria-label="Mobile buyer navigation">{links}{utilityLinks.map((link) => <Link key={link.to} className="account-nav-link" to={link.to}>{link.label}</Link>)}<SignOut /></nav></details>
            </div>
          </header>
          <main id="main" className="commerce-content"><WorkspaceContent>{children}</WorkspaceContent></main>
        </div>
      </div>
    </>;
  }
  if (workspace === "Checkout") return <div className="checkout-shell">
    <a href="#main" className="skip-link">Skip to content</a>
    <header className="checkout-header"><Link to="/" aria-label="FairPool home"><Brand /></Link><span className="checkout-secure"><Icon name="lock" />Checkout</span><HonestyLabels kinds={["sandbox"]} /></header>
    <main id="main" className="checkout-content">{children}</main>
    <footer className="checkout-footer"><Icon name="shield" /><span>PayPal Sandbox demo. No real money moves.</span><Link to="/my-pools">Back to My Pools</Link></footer>
  </div>;
  return <div className="app-layout">
    <a href="#main" className="skip-link">Skip to content</a>
    <header className="app-header"><Brand workspace={workspace} />
      {tabs.length > 0 ? <nav aria-label={`${workspace} tabs`} className="workspace-tabs">{tabs.map((tab) => <NavLink key={tab.to} to={tab.to} end={tab.end} className={({ isActive }) => isActive ? "workspace-tab is-active" : "workspace-tab"}>{tab.label}</NavLink>)}</nav> : null}
      <div className="header-utilities">{utilityLinks.length > 0 ? <nav className="utility-links" aria-label={`${workspace} settings`}>{utilityLinks.map((link) => <NavLink key={link.to} to={link.to}>{link.label}</NavLink>)}</nav> : null}<HonestyLabels kinds={["sandbox"]} /><SignOut className="shop-quiet-button" /></div>
    </header><main id="main" className="app-main"><WorkspaceContent>{children}</WorkspaceContent></main><footer className="app-footer">PayPal Sandbox demo · no real money moves</footer>
  </div>;
}
