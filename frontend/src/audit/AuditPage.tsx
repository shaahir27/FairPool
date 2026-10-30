import { PlaceholderPage, PublicLayout } from "../shared";

export function AuditPage() {
  return (
    <PublicLayout perspective="Public audit">
      <PlaceholderPage
        title="Public audit"
        route="/audit/:poolId"
        task="T09B01"
        taskTitle="Public audit page and verify-my-place"
        planned={[
          "Published rules and rules hash for the pool.",
          "Commitments, the entries root, the beacon and the lots.",
          "Awards, and the verify-my-place recompute in the browser.",
        ]}
      />
    </PublicLayout>
  );
}
