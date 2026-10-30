/**
 * Honesty labels (FR-UI-08) used by the Phase 1 shell.
 *
 * The API returns the authoritative labels on each response. These constants
 * are the shell fallback so that a placeholder screen never looks like a
 * working marketplace; replace them with response labels when a screen loads
 * data.
 *
 * `fallbackTag` is the label string in docs/contracts/api.md; `fallbackSentence`
 * is its DEP-4 notice text: "Sandbox demo: one test seller stands in for the
 * winning merchant."
 */
export const HONESTY_LABELS = {
  sandbox: "SANDBOX",
  simulated: "SIMULATED",
  mock: "MOCK",
  demoSeed: "DEMO SEED",
  fallbackTag: "FALLBACK: single stand-in seller",
  fallbackSentence:
    "Sandbox demo: one test seller stands in for the winning merchant.",
} as const;

export type HonestyLabelKind =
  | "sandbox"
  | "simulated"
  | "mock"
  | "demoSeed"
  | "fallback";
