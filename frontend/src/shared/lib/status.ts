/**
 * Status vocabulary from docs/contracts/state-machines.md.
 *
 * The API's raw value is always rendered next to the label; these maps only add
 * tone and plain words, never replace or reinterpret the value (FR-UI-08).
 */
export type StatusTone = "neutral" | "pending" | "active" | "good" | "bad";

export interface StatusStyle {
  label: string;
  tone: StatusTone;
}

export const BUYER_ORDER_STATUS: Readonly<Record<string, StatusStyle>> = {
  OFFERED: { label: "Offer sent", tone: "pending" },
  ORDER_CREATED: { label: "Approval opened", tone: "pending" },
  APPROVED: { label: "Approved in PayPal", tone: "active" },
  AUTHORIZING: { label: "Confirming the hold", tone: "active" },
  AUTHORIZED: { label: "Hold placed", tone: "active" },
  CAPTURING: { label: "Completing the payment", tone: "active" },
  CAPTURE_PENDING: { label: "Payment pending", tone: "active" },
  CAPTURED: { label: "Payment completed", tone: "good" },
  REFUNDING: { label: "Refunding", tone: "active" },
  EXPIRED: { label: "Offer expired", tone: "neutral" },
  REJECTED: { label: "Rejected", tone: "bad" },
  AUTH_FAILED: { label: "Hold failed", tone: "bad" },
  CAPTURE_FAILED: { label: "Payment failed", tone: "bad" },
  VOIDED: { label: "Hold released", tone: "neutral" },
  REFUNDED: { label: "Refunded", tone: "neutral" },
  DECLINED: { label: "Declined", tone: "neutral" },
};

export const LOT_STATUS: Readonly<Record<string, StatusStyle>> = {
  PLANNED: { label: "Planned", tone: "neutral" },
  BIDDING: { label: "Bidding", tone: "pending" },
  BID_CLOSED: { label: "Bidding closed", tone: "pending" },
  AWARDED: { label: "Awarded", tone: "active" },
  CHECKOUT_OPEN: { label: "Checkout open", tone: "active" },
  FUNDING: { label: "Funding", tone: "active" },
  FUNDED: { label: "Funded", tone: "good" },
  CLOSED: { label: "Closed", tone: "good" },
  FAILING: { label: "Failing", tone: "bad" },
  FAILED_CLOSED: { label: "Closed at net zero", tone: "bad" },
  CANCELLED: { label: "Cancelled", tone: "neutral" },
};

export const REJECT_REASON_LABELS: Readonly<Record<string, string>> = {
  DUPLICATE_PAYER: "This PayPal account was already used for another seat in this lot.",
  WRONG_COUNTRY: "PayPal reports a payer country this demo does not accept.",
  CURRENCY_MISMATCH: "The PayPal order was not in US dollars.",
  AMOUNT_MISMATCH: "The approved amount did not match the total shown.",
  PAYEE_MISMATCH: "The seller on the PayPal order was not the one we expected.",
  PAYER_MISMATCH: "The PayPal account that approved was not the one linked to this seat.",
  STATUS_NOT_APPROVED: "PayPal had not approved this order when we checked.",
};

export const TERMINAL_BUYER_ORDER_STATUSES: readonly string[] = [
  "EXPIRED",
  "REJECTED",
  "AUTH_FAILED",
  "CAPTURE_FAILED",
  "VOIDED",
  "REFUNDED",
  "DECLINED",
];

const ENTRY_STATUS: Readonly<Record<string, StatusStyle>> = {
  SUBMITTED: {label: "Entry received", tone: "pending"},
  ELIGIBLE: {label: "Entry accepted", tone: "pending"},
  SEATED: {label: "Seat allocated", tone: "active"},
  WAITLISTED: {label: "On the waiting list", tone: "pending"},
  WITHDRAWN: {label: "Withdrawn", tone: "neutral"},
  PRICED_OUT: {label: "Outside your price limit", tone: "neutral"},
};

export function statusStyle(status: string): StatusStyle {
  return (
    BUYER_ORDER_STATUS[status] ??
    LOT_STATUS[status] ?? ENTRY_STATUS[status] ?? { label: status, tone: "neutral" }
  );
}
