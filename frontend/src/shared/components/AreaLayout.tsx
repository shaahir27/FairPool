import type { ReactNode } from "react";
import { NavLink, Outlet } from "react-router-dom";

import { Brand } from "./Brand";
import { HonestyLabels } from "./HonestyLabels";

export type AreaTab = {
  to: string;
  label: string;
  end: boolean;
};

export type AreaUtilityLink = {
  to: string;
  label: string;
};

type AreaLayoutProps = {
  workspace: string;
  tabs: readonly AreaTab[];
  utilityLinks?: readonly AreaUtilityLink[];
  children?: ReactNode;
};

export function AreaLayout({
  workspace,
  tabs,
  utilityLinks = [],
  children,
}: AreaLayoutProps) {
  return (
    <div className="flex min-h-screen flex-col bg-canvas">
      <a
        href="#main"
        className="sr-only rounded-md bg-accent px-4 py-2 text-sm text-surface focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-20"
      >
        Skip to content
      </a>

      <header className="sticky top-0 z-10 border-b border-line bg-surface/90 backdrop-blur">
        <div className="mx-auto flex max-w-shell flex-wrap items-center justify-between gap-4 px-6 pb-4 pt-5">
          <Brand workspace={workspace} />
          <HonestyLabels />
        </div>
        {tabs.length > 0 ? (
          <div className="mx-auto flex max-w-shell flex-wrap items-center gap-x-4 gap-y-1 px-6">
            <nav
              aria-label={`${workspace} tabs`}
              className="flex min-w-0 flex-1 gap-1 overflow-x-auto"
            >
              {tabs.map((tab) => (
                <NavLink
                  key={tab.to}
                  to={tab.to}
                  end={tab.end}
                  className={({ isActive }) =>
                    [
                      "whitespace-nowrap border-b-2 px-3 py-3 text-sm font-medium transition-colors",
                      isActive
                        ? "border-accent text-ink"
                        : "border-transparent text-muted hover:border-line hover:text-ink",
                    ].join(" ")
                  }
                >
                  {tab.label}
                </NavLink>
              ))}
            </nav>
            {utilityLinks.length > 0 ? (
              <div className="flex shrink-0 items-center gap-4 border-l border-line pl-4 text-xs text-muted">
                {utilityLinks.map((link) => (
                  <NavLink
                    key={link.to}
                    to={link.to}
                    className="whitespace-nowrap transition-colors hover:text-ink"
                  >
                    {link.label}
                  </NavLink>
                ))}
              </div>
            ) : null}
          </div>
        ) : null}
      </header>

      <main id="main" className="mx-auto w-full max-w-shell flex-1 px-6 py-12 sm:py-16">
        {children ?? <Outlet />}
      </main>

      <footer className="border-t border-line bg-surface">
        <div className="mx-auto flex max-w-shell flex-col gap-2 px-6 py-6 text-xs text-muted sm:flex-row sm:items-center sm:justify-between">
          <p className="font-medium uppercase tracking-label">
            Phase 1 scaffold · Placeholder screens only
          </p>
          <p>No marketplace action works yet. Demonstrated in the PayPal Sandbox.</p>
        </div>
      </footer>
    </div>
  );
}
