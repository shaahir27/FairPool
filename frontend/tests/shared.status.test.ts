import { describe, expect, it } from "vitest";

import {
  BUYER_ORDER_STATUS,
  LOT_STATUS,
  REJECT_REASON_LABELS,
  TERMINAL_BUYER_ORDER_STATUSES,
  statusStyle,
} from "../src/shared/lib/status";

describe("status vocabulary", () => {
  it("covers every buyer-order state in state-machines.md", () => {
    expect(Object.keys(BUYER_ORDER_STATUS).sort()).toEqual(
      [
        "APPROVED",
        "AUTHORIZED",
        "AUTHORIZING",
        "CAPTURE_FAILED",
        "CAPTURE_PENDING",
        "CAPTURED",
        "CAPTURING",
        "DECLINED",
        "EXPIRED",
        "OFFERED",
        "ORDER_CREATED",
        "REFUNDED",
        "REFUNDING",
        "REJECTED",
        "AUTH_FAILED",
        "VOIDED",
      ].sort(),
    );
  });

  it("covers every lot state in state-machines.md", () => {
    expect(Object.keys(LOT_STATUS).sort()).toEqual(
      [
        "AWARDED",
        "BIDDING",
        "BID_CLOSED",
        "CANCELLED",
        "CHECKOUT_OPEN",
        "CLOSED",
        "FAILED_CLOSED",
        "FAILING",
        "FUNDED",
        "FUNDING",
        "PLANNED",
      ].sort(),
    );
  });

  it("marks exactly the terminal buyer-order states", () => {
    expect([...TERMINAL_BUYER_ORDER_STATUSES].sort()).toEqual(
      [
        "AUTH_FAILED",
        "CAPTURE_FAILED",
        "DECLINED",
        "EXPIRED",
        "REFUNDED",
        "REJECTED",
        "VOIDED",
      ].sort(),
    );
  });

  it("keeps the seven reject reasons readable and never renames the code", () => {
    expect(Object.keys(REJECT_REASON_LABELS)).toHaveLength(7);
    for (const [code, label] of Object.entries(REJECT_REASON_LABELS)) {
      expect(label.length).toBeGreaterThan(10);
      expect(label).not.toContain(code);
    }
  });

  it("falls back to the raw value for an unknown state", () => {
    expect(statusStyle("SOMETHING_NEW").label).toBe("SOMETHING_NEW");
    expect(statusStyle("SOMETHING_NEW").tone).toBe("neutral");
  });
});
