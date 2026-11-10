import { useParams } from "react-router-dom";

import { AreaLayout } from "../shared";

import { OfferCheckout } from "./OfferCheckout";

/** `/offers/:buyerOrderId` — standalone: a payment page carries no global tabs. */
export function OfferCheckoutPage() {
  const { buyerOrderId } = useParams<{ buyerOrderId: string }>();
  return (
    <div className="buyer-workspace"><AreaLayout workspace="Checkout" tabs={[]}>
      {buyerOrderId ? (
        <OfferCheckout buyerOrderId={buyerOrderId} />
      ) : (
        <p className="p-8 text-sm text-muted">This offer link is incomplete.</p>
      )}
    </AreaLayout></div>
  );
}
