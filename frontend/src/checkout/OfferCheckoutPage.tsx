import { AreaLayout, PlaceholderPage } from "../shared";

export function OfferCheckoutPage() {
  return (
    <AreaLayout workspace="Checkout" tabs={[]}>
      <PlaceholderPage
        title="Offer checkout"
        route="/offers/:buyerOrderId"
        task="T05A02"
        taskTitle="Checkout UI"
        planned={[
          "The offer disclosure: merchant, product, delivery and return terms, totals and the buyer's cap.",
          "The PayPal approval step and its redirect fallback.",
          "The order status card after approval.",
        ]}
      />
    </AreaLayout>
  );
}
