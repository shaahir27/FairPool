import { AreaLayout, type AreaTab, type AreaUtilityLink } from "../shared";

/** Buyer tabs fixed by FR-UI-01 to FR-UI-03 (scaffold section 12). */
const BUYER_TABS: readonly AreaTab[] = [
  { to: "/", label: "Discover and Join", end: true },
  { to: "/my-pools", label: "My Pools", end: false },
  { to: "/orders", label: "Orders", end: false },
];

const BUYER_UTILITY_LINKS: readonly AreaUtilityLink[] = [
  { to: "/settings/paypal", label: "PayPal settings" },
  { to: "/settings/agents", label: "Agent settings" },
];

export function BuyerLayout() {
  return (
    <AreaLayout
      workspace="Buyer workspace"
      tabs={BUYER_TABS}
      utilityLinks={BUYER_UTILITY_LINKS}
    />
  );
}
