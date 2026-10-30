import { AreaLayout, PlaceholderPage, type AreaTab } from "../shared";

const OPS_TABS: readonly AreaTab[] = [
  { to: "/ops", label: "Overview", end: false },
];

export function OpsPage() {
  return (
    <AreaLayout workspace="Ops console" tabs={OPS_TABS}>
      <PlaceholderPage
        title="Ops console"
        route="/ops/*"
        task="T07A04"
        taskTitle="Ops console v1"
        planned={[
          "Lot state views and the abort action.",
          "Dead-letter webhook events and their retry action.",
          "Running the reconciler, mock toggles with MOCK labels, alerts and the audit export.",
        ]}
      />
    </AreaLayout>
  );
}
