import { PlaceholderPage } from "../shared";

export function FulfillmentPage() {
  return (
    <PlaceholderPage
      title="Fulfillment"
      route="/merchant/fulfillment"
      task="T08A02"
      taskTitle="Fulfillment tab UI"
      planned={[
        "Funded lots and the shipping CSV for each one.",
        "Marking orders shipped with carrier and tracking number.",
        "The verification manifest download and the verification result.",
      ]}
    />
  );
}
