/**
 * Pure grouping and tracker arithmetic for the Active Bids screen.
 *
 * Design 11.6: holds are counted against the MOQ until captures begin, then
 * captures are counted against it. The tracker only presents the counts the
 * progress endpoint publishes; it never infers a payment (I4).
 */

export type BidSection = "pending" | "checkout" | "lost";

export function bidGroup(status: string): BidSection {
  if (status === "AWARDED") return "checkout";
  if (status === "LOST" || status === "REJECTED") return "lost";
  // DRAFT, PROPOSED, CONFIRMED, FLAGGED, ELIGIBLE and any status this console
  // does not know yet stay visible and actionable rather than disappear.
  return "pending";
}

export interface TrackerInput {
  moq: number;
  holds_placed: number;
  captures_completed: number;
}

export interface Tracker {
  phase: "holds" | "captures";
  primary: number;
  target: number;
  remaining: number;
  met: boolean;
  fraction: number;
}

export function trackerOf(input: TrackerInput): Tracker {
  const target = Math.max(0, input.moq);
  const phase = input.captures_completed > 0 ? "captures" : "holds";
  const primary =
    phase === "captures" ? input.captures_completed : input.holds_placed;
  return {
    phase,
    primary,
    target,
    remaining: Math.max(0, target - primary),
    // No published minimum is not a met minimum; the screen never guesses one.
    met: target > 0 && primary >= target,
    fraction: target > 0 ? Math.min(1, Math.max(0, primary / target)) : 0,
  };
}
