import type { ApiComponents } from "../shared";

/** The declared admin lot view; the ops route returns exactly these fields. */
export type AdminLot = ApiComponents["schemas"]["AdminLotView"];

export type ApiFailure = { code: string; message: string };

/**
 * One alert row from `GET /api/v1/admin/alerts`. The route returns derived rows
 * with per-kind keys, so the optional fields mirror `ops.alerts` exactly.
 */
export type AlertRow = {
  kind: string;
  event_id?: string;
  paypal_event_id?: string;
  event_type?: string;
  status?: string;
  received_at?: string;
  lot_id?: string;
  pool_id?: string;
  fund_deadline_at?: string;
  buyer_order_id?: string;
  paypal_auth_id?: string;
  age_s?: number;
  failing_since?: string;
};

export type DeadLetterEvent = {
  id: string;
  paypal_event_id: string;
  event_type: string;
  status: string;
  verified: boolean;
  verification_detail: string | null;
  received_at: string;
};

export type MockKind = "paypal_mock_response" | "force_capture_failure" | "delay_webhooks";

export type MockToggle = { kind: MockKind; value: string | null; ttl_s: number; labels: string[] };

export const MOCK_KINDS: readonly { kind: MockKind; label: string; hint: string }[] = [
  {
    kind: "paypal_mock_response",
    label: "Mock PayPal response",
    hint: "Sets PayPal-Mock-Response on the next adapter call. Use a spike-verified code such as DUPLICATE_INVOICE_ID.",
  },
  {
    kind: "force_capture_failure",
    label: "Force capture failure",
    hint: "The next capture is declined without calling PayPal, so the real authorization stays voidable.",
  },
  {
    kind: "delay_webhooks",
    label: "Delay webhooks",
    // Verbatim from the API's own docstring (api/schemas.py): it records and labels only.
    hint: "delay_webhooks is recorded and labelled only: it does not delay delivery.",
  },
];

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** The admin routes take a UUID path segment; refuse anything else before a request. */
export function isLotId(value: string): boolean {
  return UUID.test(value);
}

/**
 * Read the API error envelope without trusting it: an unknown or HTML body must
 * never surface as raw exception text (config-and-errors.md section 2).
 */
export function failureOf(failure: unknown, fallbackMessage: string): ApiFailure {
  const envelope = failure as { error?: { code?: unknown; message?: unknown } } | undefined;
  return {
    code: typeof envelope?.error?.code === "string" ? envelope.error.code : "REQUEST_FAILED",
    message:
      typeof envelope?.error?.message === "string" ? envelope.error.message : fallbackMessage,
  };
}

export function shortId(value: string): string {
  return value.length > 13 ? `${value.slice(0, 8)}…` : value;
}
