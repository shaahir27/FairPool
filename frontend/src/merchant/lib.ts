/**
 * Merchant-console helpers.
 *
 * The feed accelerates; the JSON refetch decides (api.md section 4.2). Neither the
 * browser clock nor the feed payload is used for a deadline: a `tick` only supplies
 * the database's `server_time` sample that `useCountdown` is allowed to age.
 *
 * The response/label/name helpers live in shared so every workspace uses one copy.
 */
import { useEffect, useRef } from "react";

import { API_BASE_URL } from "../shared";

export {
  envelope as failureEnvelope,
  honestyKinds as labelsFrom,
  productName,
  shortId,
} from "../shared";

export interface MerchantEvent {
  type: "tick" | "lot_open" | "bid_status" | "checkout_progress";
  server_time?: string;
}

const EVENT_NAMES: readonly MerchantEvent["type"][] = [
  "tick",
  "lot_open",
  "bid_status",
  "checkout_progress",
];

export function useMerchantEvents(onEvent: (event: MerchantEvent) => void): void {
  const handler = useRef(onEvent);
  useEffect(() => {
    handler.current = onEvent;
  }, [onEvent]);

  useEffect(() => {
    // jsdom and older browsers have no EventSource; the screen still loads and
    // refreshes from its own requests, it just does not accelerate.
    if (typeof EventSource === "undefined") return;
    let timer: number | null = null;
    const source = new EventSource(`${API_BASE_URL}/api/v1/merchant/events`, {
      withCredentials: true,
    });
    const listeners = EVENT_NAMES.map((name) => {
      const listener = (event: Event) => {
        let serverTime: string | undefined;
        const data = (event as MessageEvent<string>).data;
        if (typeof data === "string" && data.length > 0) {
          try {
            const parsed = JSON.parse(data) as { server_time?: unknown };
            if (typeof parsed.server_time === "string") serverTime = parsed.server_time;
          } catch {
            // The feed's detail is optional; the event name alone refreshes the screen.
          }
        }
        if (timer !== null) window.clearTimeout(timer);
        timer = window.setTimeout(() => {
          handler.current({ type: name, ...(serverTime ? { server_time: serverTime } : {}) });
        }, 400);
      };
      source.addEventListener(name, listener);
      return { name, listener };
    });
    return () => {
      for (const { name, listener } of listeners) source.removeEventListener(name, listener);
      if (timer !== null) window.clearTimeout(timer);
      source.close();
    };
  }, []);
}
