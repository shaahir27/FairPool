import { AuthLayout, PlaceholderPage } from "../shared";

const DISCOVER_TASK = {
  task: "T06B05",
  taskTitle: "Buyer UI v1: Discover and Join",
} as const;

export function DiscoverPage() {
  return (
    <PlaceholderPage
      title="Discover and Join"
      route="/"
      task={DISCOVER_TASK.task}
      taskTitle={DISCOVER_TASK.taskTitle}
      planned={[
        "The prompt bar and the manual request form for intake.",
        "Open pools with their public entry counts.",
        "The confirmation card, the join action and the entry receipt.",
      ]}
    />
  );
}

export function MyPoolsPage() {
  return (
    <PlaceholderPage
      title="My Pools"
      route="/my-pools"
      task="T07B01"
      taskTitle="Buyer UI v2: My Pools and Orders"
      planned={[
        "Pending entries for open, closed and bidding pools.",
        "Waitlist positions reported by the allocation.",
        "Action-required entries with the offer countdown and checkout hand-off.",
        "Reasons for priced-out and rejected entries.",
      ]}
    />
  );
}

export function OrdersPage() {
  return (
    <PlaceholderPage
      title="Orders"
      route="/orders"
      task="T07B01"
      taskTitle="Buyer UI v2: My Pools and Orders"
      planned={[
        "Orders grouped by outcome.",
        "A receipt with amounts, PayPal capture ID, winning merchant and return terms.",
        "Status history for each order.",
      ]}
    />
  );
}

export function BuyerOrderPage() {
  return (
    <PlaceholderPage
      title="Order detail"
      route="/orders/:buyerOrderId"
      task="T07B01"
      taskTitle="Buyer UI v2: My Pools and Orders"
      planned={[
        "Order and lot status with the API-provided honesty labels.",
        "Payment status for authorization, capture and refund.",
        "The receipt and status history for this order.",
      ]}
    />
  );
}

export function PoolPage() {
  return (
    <PlaceholderPage
      title="Pool lobby"
      route="/pools/:poolId"
      task="T06B05"
      taskTitle="Buyer UI v1: Discover and Join"
      planned={[
        "Pool detail, timeline and published rules link.",
        "Live pool status from the server-sent events stream.",
        "My entry status and the route back to my pools.",
      ]}
    />
  );
}

export function PayPalSettingsPage() {
  return (
    <PlaceholderPage
      title="PayPal settings"
      route="/settings/paypal"
      task="T07B01"
      taskTitle="Buyer UI v2: My Pools and Orders"
      planned={[
        "The current PayPal link state for the signed-in buyer.",
        "The vault consent version and saved-payment state in vault mode.",
        "The unlink action and the server's refusal while active entries exist.",
      ]}
    />
  );
}

export function AgentSettingsPage() {
  return (
    <PlaceholderPage
      title="Agent settings"
      route="/settings/agents"
      task="T07B01"
      taskTitle="Buyer UI v2: My Pools and Orders"
      planned={[
        "Agent delegation tokens with the create, list and revoke actions.",
        "A token secret shown once at creation.",
        "A pointer to the agent API documentation.",
      ]}
    />
  );
}

export function LoginPage() {
  return (
    <AuthLayout>
      <PlaceholderPage
        title="Log in"
        route="/login"
        task="T06B05"
        taskTitle="Buyer UI v1: Discover and Join"
        planned={[
          "Email and password sign-in against the session API.",
          "The signed-in buyer's PayPal link state.",
          "Redirect to the requested buyer screen after sign-in.",
        ]}
      />
    </AuthLayout>
  );
}

export function RegisterPage() {
  return (
    <AuthLayout>
      <PlaceholderPage
        title="Register"
        route="/register"
        task="T06B05"
        taskTitle="Buyer UI v1: Discover and Join"
        planned={[
          "Account creation against the session API.",
          "The role assigned by the server for a new account.",
          "Redirect to the buyer Discover and Join screen.",
        ]}
      />
    </AuthLayout>
  );
}
