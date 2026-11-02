import type { ReactNode } from "react";
import { MotionConfig } from "motion/react";
import { Link, NavLink, Outlet } from "react-router-dom";
import { Brand } from "./Brand";
import { HonestyLabels } from "./HonestyLabels";
import { Icon } from "./Icon";
import "../commerce.css";

export type AreaTab = { to: string; label: string; end: boolean };
export type AreaUtilityLink = { to: string; label: string };
type AreaLayoutProps = { workspace: string; tabs: readonly AreaTab[]; utilityLinks?: readonly AreaUtilityLink[]; children?: ReactNode };

export function AreaLayout({ workspace, tabs, utilityLinks = [], children }: AreaLayoutProps) {
  if (workspace === "Buyer workspace") {
    const links = tabs.map((tab, index) => (
      <NavLink key={tab.to} to={tab.to} end={tab.end} className={({ isActive }) => `account-nav-link ${isActive ? "is-active" : ""}`}>
        <Icon name={index === 0 ? "search" : index === 1 ? "layers" : "bag"} />
        <span>{tab.label}</span><Icon name="chevron" className="nav-chevron" />
      </NavLink>
    ));
    return <MotionConfig reducedMotion="user">
      <div className="commerce-shell">
        <a href="#main" className="skip-link">Skip to content</a>
        <aside className="account-sidebar">
          <Link to="/" aria-label="FairPool home"><Brand /></Link>
          <p className="sidebar-caption">Your shopping space</p>
          <nav aria-label={`${workspace} tabs`} className="account-navigation">{links}</nav>
          <div className="sidebar-bottom">
            <nav aria-label={`${workspace} settings`} className="account-navigation secondary-navigation">
              {utilityLinks.map((link) => <NavLink key={link.to} to={link.to} className="account-nav-link"><Icon name={link.to.includes("paypal") ? "wallet" : "settings"} /><span>{link.label}</span></NavLink>)}
            </nav>
            <div className="sidebar-note"><Icon name="layers" /><strong>A better price, together.</strong><p>One pool. A shared opportunity. Your own order.</p></div>
            <p className="sidebar-demo">PayPal Sandbox demo<br />No real money moves.</p>
          </div>
        </aside>
        <div className="commerce-workspace">
          <header className="account-topbar">
            <div className="account-mobile-brand"><Link to="/" aria-label="FairPool home"><Brand /></Link></div>
            <span className="account-context">Your account</span>
            <div className="account-topbar-right"><HonestyLabels kinds={["sandbox"]} />
              <details className="account-mobile-menu" onClick={(event) => { if ((event.target as Element).closest("a")) event.currentTarget.open = false; }} onKeyDown={(event) => { if (event.key === "Escape") { event.currentTarget.open = false; event.currentTarget.querySelector("summary")?.focus(); } }}><summary><Icon name="menu" /><span className="sr-only">Open account navigation</span></summary><nav aria-label="Mobile buyer navigation">{links}{utilityLinks.map((link) => <Link key={link.to} className="account-nav-link" to={link.to}>{link.label}</Link>)}</nav></details>
            </div>
          </header>
          <main id="main" className="commerce-content">{children ?? <Outlet />}</main>
        </div>
      </div>
    </MotionConfig>;
  }
  if (workspace === "Checkout") return <MotionConfig reducedMotion="user"><div className="checkout-shell">
    <a href="#main" className="skip-link">Skip to content</a>
    <header className="checkout-header"><Link to="/" aria-label="FairPool home"><Brand /></Link><span className="checkout-secure"><Icon name="lock" />Checkout</span><HonestyLabels kinds={["sandbox"]} /></header>
    <main id="main" className="checkout-content">{children}</main>
    <footer className="checkout-footer"><Icon name="shield" /><span>PayPal Sandbox demo. No real money moves.</span><Link to="/my-pools">Back to My Pools</Link></footer>
  </div></MotionConfig>;
  return <div className="app-layout">
    <a href="#main" className="skip-link">Skip to content</a>
    <header className="app-header"><Brand workspace={workspace} />
      {tabs.length > 0 ? <nav aria-label={`${workspace} tabs`} className="workspace-tabs">{tabs.map((tab) => <NavLink key={tab.to} to={tab.to} end={tab.end} className={({ isActive }) => isActive ? "workspace-tab is-active" : "workspace-tab"}>{tab.label}</NavLink>)}</nav> : null}
      <div className="header-utilities">{utilityLinks.length > 0 ? <nav className="utility-links" aria-label={`${workspace} settings`}>{utilityLinks.map((link) => <NavLink key={link.to} to={link.to}>{link.label}</NavLink>)}</nav> : null}<HonestyLabels kinds={["sandbox"]} /></div>
    </header><main id="main" className="app-main">{children ?? <Outlet />}</main><footer className="app-footer">PayPal Sandbox demo · no real money moves</footer>
  </div>;
}
