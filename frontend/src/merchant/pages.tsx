import { PlaceholderPage } from "../shared";

export function DemandPage() {
  return (
    <PlaceholderPage
      title="Demand Board"
      route="/merchant/demand"
      task="T08B01"
      taskTitle="Merchant console UI I: Demand Board and bid submission"
      planned={[
        "A live feed of lots open for bidding with their requirement summaries.",
        "Search over those lots.",
        "Quote paste (proposed fields) and the structured sealed-bid form.",
      ]}
    />
  );
}

export function BidsPage() {
  return (
    <PlaceholderPage
      title="Active Bids"
      route="/merchant/bids"
      task="T08B02"
      taskTitle="Merchant console UI II: Active Bids and Developer API"
      planned={[
        "Pending bids.",
        "Checkout progress against the minimum for the awarded lot.",
        "Lost or failed bids with their reason codes.",
      ]}
    />
  );
}

export function DeveloperPage() {
  return (
    <PlaceholderPage
      title="Developer API"
      route="/merchant/developer"
      task="T08B02"
      taskTitle="Merchant console UI II: Active Bids and Developer API"
      planned={[
        "API key creation and revocation, with the secret shown once.",
        "Scopes and rate limits for the Merchant Agent API.",
        "SDK downloads, the portal link and a quickstart.",
      ]}
    />
  );
}

export function ProfilePage() {
  return (
    <PlaceholderPage
      title="Merchant profile"
      route="/merchant/profile"
      task="T08B01"
      taskTitle="Merchant console UI I: Demand Board and bid submission"
      planned={[
        "The merchant display name used on offers.",
        "Self-declared attestations and their accepted state.",
        "The seller onboarding entry point where the server offers one.",
      ]}
    />
  );
}
