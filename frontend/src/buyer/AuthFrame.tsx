import type { ReactNode } from "react";

import { AuthAside, AuthLayout, HonestyLabels } from "../shared";

export function AuthFrame({ headline, valueLine, children }: {
  headline: string; valueLine: string; children: ReactNode;
}) {
  return (
    <AuthLayout>
      <AuthAside headline={headline} valueLine={valueLine} />
      <section className="auth-panel">
        <div className="auth-label"><HonestyLabels kinds={["sandbox"]} /></div>
        <div id="auth-form" className="auth-form">{children}</div>
        <p className="auth-footnote">Your PayPal password stays with PayPal. Connecting an account does not charge you.</p>
      </section>
    </AuthLayout>
  );
}
