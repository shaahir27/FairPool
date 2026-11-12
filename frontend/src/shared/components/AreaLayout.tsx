import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { Suspense, type ReactNode } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { Brand } from "./Brand";
import { HonestyLabels } from "./HonestyLabels";
import { Icon } from "./Icon";
import { LoadingScreen } from "./LoadingScreen";
import { NotificationInbox } from "./NotificationInbox";
import { api } from "../api/client";
import { setCsrfToken } from "../lib/csrf";
import { accountState, resetSessionCache, subscribeAccount } from "../lib/session";
import { prefetchWorkspace } from "../api/prefetch";
import { useRefreshingReads } from "../api/reads";
import "../commerce.css";

export type AreaTab = { to: string; label: string; end: boolean };
export type AreaUtilityLink = { to: string; label: string };
type AreaLayoutProps = { workspace: string; tabs: readonly AreaTab[]; utilityLinks?: readonly AreaUtilityLink[]; onPrefetch?: (to: string) => void; children?: ReactNode };

function WorkspaceContent({ children }: { children?: ReactNode }) {
  return <Suspense fallback={<LoadingScreen label="Loading workspace page" compact />}>
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
function SignOut({ className = "account-nav-link account-signout" }: { className?: string }) {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  const signOut = async () => {
    if (busy) return;
    setBusy(true);
    setFailed(false);
    try {
      // Another tab may have replaced the cookie since this tab last checked /me.
      const { response } = await api.GET("/api/v1/me");
      if (!response.ok && response.status !== 401) {
        setFailed(true);
        return;
      }
      if (response.ok) {
        const { error } = await api.POST("/api/v1/auth/logout");
        if (error) {
          setFailed(true);
          return;
        }
      }
      setCsrfToken(null);
      resetSessionCache("out");
      navigate(pathname.startsWith("/merchant/") ? "/login?role=merchant" : "/login", { replace: true });
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <button type="button" className={className} disabled={busy} onClick={() => void signOut()}>
        <Icon name="logout" />
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

function AccountMenu({ links, title, label }: { links: readonly AreaUtilityLink[]; title: string; label: string }) {
  const menu = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    const closeOutside = (event: PointerEvent) => {
      if (menu.current?.open && event.target instanceof Node && !menu.current.contains(event.target)) menu.current.open = false;
    };
    document.addEventListener("pointerdown", closeOutside);
    return () => document.removeEventListener("pointerdown", closeOutside);
  }, []);
  return <details ref={menu} className="account-mobile-menu"
    onClick={(event) => { if ((event.target as Element).closest("a")) event.currentTarget.open = false; }}
    onKeyDown={(event) => { if (event.key === "Escape") { event.currentTarget.open = false; event.currentTarget.querySelector("summary")?.focus(); } }}>
    <summary aria-label="Open account navigation"><Icon name="user" /><span>Account</span><Icon name="down" /></summary>
    <nav aria-label={label}><p className="mobile-menu-title">{title}</p>
      {links.map((link) => <NavLink onMouseEnter={() => prefetchWorkspace(link.to)} onFocus={() => prefetchWorkspace(link.to)} onPointerDown={() => prefetchWorkspace(link.to)} key={link.to} className={({isActive}) => `account-nav-link${isActive ? " is-active" : ""}`} to={link.to}><Icon name={link.to.includes("paypal") ? "wallet" : link.to.includes("addresses") ? "truck" : "shield"} /><span>{link.label}</span></NavLink>)}
      <SignOut />
    </nav>
  </details>;
}

export function AreaLayout({
  workspace,
  tabs,
  utilityLinks = [],
  onPrefetch,
  children,
}: AreaLayoutProps) {
  const account = useSyncExternalStore(subscribeAccount, accountState);
  const refreshing = useRefreshingReads();
  const warm = onPrefetch ?? prefetchWorkspace;
  if (workspace === "Buyer workspace" || workspace === "Ops console" || workspace === "Merchant workspace") {
    const admin = workspace === "Ops console";
    const merchant = workspace === "Merchant workspace";
    const home = admin ? "/ops" : merchant ? "/merchant/demand" : "/discover";
    const firstName = account ? account.display_name.split(" ")[0] : null;
    const links = tabs.map((tab, index) => (
      <NavLink
        key={tab.to}
        to={tab.to}
        end={tab.end}
        onMouseEnter={() => warm(tab.to)}
        onFocus={() => warm(tab.to)}
        onPointerDown={() => warm(tab.to)}
        className={({ isActive }) => `account-nav-link ${isActive ? "is-active" : ""}`}
      >
        <Icon name={merchant ? (index === 0 ? "search" : index === 1 ? "layers" : index === 2 ? "bag" : "settings") : admin ? (index === 0 ? "shield" : index === 1 ? "layers" : index === 2 ? "returns" : "receipt") : index === 0 ? "search" : index === 1 ? "layers" : "bag"} />
        <span>{tab.label}</span><Icon name="chevron" className="nav-chevron" />
      </NavLink>
    ));
    return <>
      <div className={`commerce-shell${admin ? " ops-workspace-shell" : merchant ? " merchant-workspace-shell" : ""}`}>
        <a href="#main" className="skip-link">Skip to content</a>
        <aside className="account-sidebar" aria-label="Workspace sidebar">
          <Link to={home} aria-label="FairPool home"><Brand /></Link>
          {merchant ? <div className="sidebar-hello"><p className="sidebar-hello-name">Merchant workspace</p><p className="sidebar-hello-state"><Icon name="bag" />Supply, bids and deliveries</p></div> : admin ? <div className="sidebar-hello"><p className="sidebar-hello-name">Administration</p><p className="sidebar-hello-state"><Icon name="shield" />Platform operations</p></div> : account ? (
            <div className="sidebar-hello">
              <p className="sidebar-hello-name">Hi{firstName ? `, ${firstName}` : ""}</p>
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
          <div className="sidebar-nav-scroll">
            <nav aria-label={`${workspace} tabs`} className="account-navigation">{links}</nav>
            <nav aria-label={`${workspace} settings`} className="account-navigation secondary-navigation">
              {utilityLinks.map((link) => <NavLink onMouseEnter={() => prefetchWorkspace(link.to)} onFocus={() => prefetchWorkspace(link.to)} onPointerDown={() => prefetchWorkspace(link.to)} key={link.to} to={link.to} className={({isActive}) => `account-nav-link${isActive ? " is-active" : ""}`}><Icon name={link.to.includes("paypal") ? "wallet" : link.to.includes("addresses") ? "truck" : "shield"} /><span>{link.label}</span></NavLink>)}
            </nav>
          </div>
          <div className="sidebar-bottom">
            {account ? <div className="sidebar-account"><span className="sidebar-avatar" aria-hidden="true">{firstName?.slice(0, 1).toUpperCase()}</span><div><strong title={account.display_name}>{account.display_name}</strong><span>{admin ? "Administrator" : merchant ? "Merchant" : "Buyer account"}</span></div></div> : null}
            <SignOut />
            <p className="sidebar-demo">Sandbox demo. No real money moves</p>
          </div>
        </aside>
        <div className="commerce-workspace">
          <header className="account-topbar">
            <div className="account-mobile-brand"><Link to={home} aria-label="FairPool home"><Brand /></Link></div>
            <span className="account-context">{merchant ? (account?.display_name ? `${account.display_name} - Merchant` : "Merchant workspace") : admin ? (account?.display_name ? `${account.display_name} · Administrator` : "Administrator") : account ? `${account.display_name}'s account` : "Your account"}</span>
            <div className="account-topbar-right">{admin ? null : <NotificationInbox />}<HonestyLabels kinds={["sandbox"]} />
              <AccountMenu links={utilityLinks} title={merchant ? "Merchant account" : admin ? "Administration" : "Your account"} label={merchant ? "Mobile merchant navigation" : admin ? "Mobile admin navigation" : "Mobile buyer navigation"} />
            </div>
          </header>
          <nav className="mobile-primary-navigation" aria-label={merchant ? "Mobile merchant workspace navigation" : admin ? "Mobile admin workspace navigation" : "Mobile shopping navigation"}>{links}</nav>
          <main id="main" className="commerce-content"><p role="status" aria-live="polite" className="text-xs text-muted min-h-[1.25rem]">{refreshing ? "Updating information..." : null}</p><WorkspaceContent>{children}</WorkspaceContent></main>
        </div>
      </div>
    </>;
  }
  if (workspace === "Checkout") return <div className="checkout-shell">
    <a href="#main" className="skip-link">Skip to content</a>
    <header className="checkout-header"><Link to="/discover" aria-label="FairPool home"><Brand /></Link><span className="checkout-secure"><Icon name="lock" />Checkout</span><HonestyLabels kinds={["sandbox"]} /></header>
    <main id="main" className="checkout-content">{children}</main>
    <footer className="checkout-footer"><Icon name="shield" /><span>PayPal Sandbox demo. No real money moves.</span><Link to="/my-pools">Back to My Pools</Link></footer>
  </div>;
  return <div className="app-layout">
    <a href="#main" className="skip-link">Skip to content</a>
    <header className="app-header"><Brand workspace={workspace} />
      {tabs.length > 0 ? <nav aria-label={`${workspace} tabs`} className="workspace-tabs">{tabs.map((tab) => <NavLink key={tab.to} to={tab.to} end={tab.end} className={({ isActive }) => isActive ? "workspace-tab is-active" : "workspace-tab"}>{tab.label}</NavLink>)}</nav> : null}
      <div className="header-utilities">{utilityLinks.length > 0 ? <nav className="utility-links" aria-label={`${workspace} settings`}>{utilityLinks.map((link) => <NavLink onMouseEnter={() => prefetchWorkspace(link.to)} onFocus={() => prefetchWorkspace(link.to)} onPointerDown={() => prefetchWorkspace(link.to)} key={link.to} to={link.to}>{link.label}</NavLink>)}</nav> : null}<HonestyLabels kinds={["sandbox"]} /><SignOut className="shop-quiet-button" /></div>
    </header><main id="main" className="app-main"><WorkspaceContent>{children}</WorkspaceContent></main><footer className="app-footer">PayPal Sandbox demo · no real money moves</footer>
  </div>;
}
