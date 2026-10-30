import type { ReactNode } from "react";

import { Brand } from "./Brand";
import { HonestyLabels } from "./HonestyLabels";

type AuthLayoutProps = {
  children: ReactNode;
};

export function AuthLayout({ children }: AuthLayoutProps) {
  return (
    <div className="flex min-h-screen flex-col bg-canvas">
      <header className="mx-auto flex w-full max-w-shell flex-wrap items-center justify-between gap-4 px-6 py-6">
        <Brand workspace="Buyer account" />
        <HonestyLabels />
      </header>
      <main className="flex flex-1 items-start justify-center px-6 pb-16 pt-8 sm:items-center sm:pt-0">
        <div className="w-full max-w-3xl">{children}</div>
      </main>
      <footer className="mx-auto w-full max-w-shell px-6 pb-8 text-xs text-muted">
        <p className="font-medium uppercase tracking-label">
          Phase 1 scaffold · Placeholder screens only
        </p>
      </footer>
    </div>
  );
}
