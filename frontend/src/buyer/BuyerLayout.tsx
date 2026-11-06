import type { ReactNode } from "react";

import { AreaLayout, type AreaTab, type AreaUtilityLink } from "../shared";
import { prefetchBuyer } from "./prefetch";

/** Buyer tabs fixed by FR-UI-01 to FR-UI-03 (scaffold section 12). */
const BUYER_TABS: readonly AreaTab[] = [
  { to: "/discover", label: "Discover and Join", end: true },
  { to: "/my-pools", label: "My Pools", end: false },
  { to: "/orders", label: "Orders", end: false },
];

const BUYER_UTILITY_LINKS: readonly AreaUtilityLink[] = [
  { to: "/settings/paypal", label: "PayPal settings" },
  { to: "/settings/addresses", label: "Delivery addresses" },
  { to: "/settings/agents", label: "Agent settings" },
];

export function BuyerLayout({ children }: { children?: ReactNode }) {
  return (
    <AreaLayout
      workspace="Buyer workspace"
      tabs={BUYER_TABS}
      utilityLinks={BUYER_UTILITY_LINKS}
      onPrefetch={prefetchBuyer}
    >
      {children}
    </AreaLayout>
  );
}
