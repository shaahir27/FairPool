import { AreaLayout, type AreaTab, type AreaUtilityLink } from "../shared";

/** Merchant tabs fixed by FR-UI-04 to FR-UI-07 (scaffold section 12). */
const MERCHANT_TABS: readonly AreaTab[] = [
  { to: "/merchant/demand", label: "Demand Board", end: false },
  { to: "/merchant/bids", label: "Active Bids", end: false },
  { to: "/merchant/fulfillment", label: "Fulfillment", end: false },
  { to: "/merchant/developer", label: "Developer API", end: false },
];

const MERCHANT_UTILITY_LINKS: readonly AreaUtilityLink[] = [
  { to: "/merchant/profile", label: "Profile" },
];

export function MerchantLayout() {
  return (
    <AreaLayout
      workspace="Merchant workspace"
      tabs={MERCHANT_TABS}
      utilityLinks={MERCHANT_UTILITY_LINKS}
    />
  );
}
