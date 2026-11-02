import type { ReactNode } from "react";

export function AuthLayout({ children }: { children: ReactNode }) {
  return <main className="auth-layout"><a className="skip-link" href="#auth-form">Skip to form</a>{children}</main>;
}
