/**
 * Server-clock countdown and the one place the View Transition API is touched.
 *
 * The label re-renders once a second; the ring is written straight to the SVG
 * element so a frame never goes through React (animation-performance: no state
 * per frame, no inherited CSS variable). The countdown is presentation only:
 * every handler re-checks `offer_expires_at` on the server (I15).
 */
import { type RefObject, useEffect, useRef, useState } from "react";
import { flushSync } from "react-dom";

export interface Countdown {
  label: string;
  remainingMs: number;
  fractionElapsed: number;
  expired: boolean;
  urgent: boolean;
  ringRef: RefObject<SVGCircleElement>;
}

const RING_CIRCUMFERENCE = 2 * Math.PI * 18;

function formatRemaining(ms: number): string {
  const total = Math.max(0, Math.ceil(ms / 1000));
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}

export function useCountdown(
  expiresAt: string,
  serverNow: string,
  startedAt?: string | null,
): Countdown {
  const expires = Date.parse(expiresAt);
  const started = startedAt ? Date.parse(startedAt) : Number.NaN;
  // I15: keep the sample stable across ticks; recomputing an offset freezes time.
  const sample = useRef({ serverNow, sampledAt: performance.now() });
  if (sample.current.serverNow !== serverNow) {
    sample.current = { serverNow, sampledAt: performance.now() };
  }
  const sampledAt = sample.current.sampledAt;
  const serverTime = Date.parse(serverNow);
  const windowMs = Number.isFinite(started) && expires > started ? expires - started : 0;

  const [remainingMs, setRemainingMs] = useState(() =>
    Math.max(0, expires - (serverTime + performance.now() - sampledAt)),
  );
  const ringRef = useRef<SVGCircleElement>(null);

  useEffect(() => {
    const tick = () => {
      const next = Math.max(0, expires - (serverTime + performance.now() - sampledAt));
      setRemainingMs(next);
      if (ringRef.current && windowMs > 0) {
        const elapsed = Math.min(1, Math.max(0, 1 - next / windowMs));
        ringRef.current.style.strokeDashoffset = String(RING_CIRCUMFERENCE * (1 - elapsed));
      }
    };
    tick();
    const id = window.setInterval(tick, 1000);
    return () => window.clearInterval(id);
  }, [expires, serverTime, sampledAt, windowMs]);

  const fractionElapsed =
    windowMs > 0 ? Math.min(1, Math.max(0, 1 - remainingMs / windowMs)) : 0;

  return {
    label: formatRemaining(remainingMs),
    remainingMs,
    fractionElapsed,
    expired: remainingMs <= 0,
    urgent: remainingMs > 0 && remainingMs <= 60_000,
    ringRef,
  };
}

type ViewTransitionDocument = Document & {
  startViewTransition?: (callback: () => void) => { skipTransition: () => void };
};

let active: { skipTransition: () => void } | null = null;

/** Depth of each surface, so a slide only happens when it means something. */
const DEPTH: ReadonlyArray<readonly [string, number]> = [
  ["/settings", 1],
  ["/my-pools", 1],
  ["/orders", 1],
  ["/offers", 2],
  ["/pools", 2],
];

function depthOf(path: string): number {
  const match = DEPTH.find(([prefix]) => path.startsWith(prefix));
  return match ? match[1] : 1;
}

/**
 * Wrap a navigation in a same-document view transition.
 *
 * React Router 6.28 has no `viewTransition` prop (that is v7), and the transition
 * must not resolve before React commits, hence `flushSync`. Browsers without the
 * API navigate instantly; reduced-motion users get the same plain navigation.
 */
export function startRouteTransition(
  navigate: () => void,
  from: string,
  to: string,
): void {
  const doc = document as ViewTransitionDocument;
  const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  if (!doc.startViewTransition || reduced) {
    navigate();
    return;
  }
  active?.skipTransition();
  const direction = depthOf(to) >= depthOf(from) ? "forwards" : "backwards";
  document.documentElement.dataset.navDirection = direction;
  active = doc.startViewTransition(() => {
    // React commits synchronously so the snapshot sees the destination screen.
    flushSync(navigate);
  });
}
