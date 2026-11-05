/**
 * Small presentation helpers shared by every workspace.
 *
 * These were duplicated per area; one copy keeps the API-failure shape, the
 * honesty-label mapping and the short product/id wording identical everywhere.
 */
import { HONESTY_LABELS, type HonestyLabelKind } from "./labels";

/** The API's error envelope, with a plain fallback that never leaks raw text. */
export function envelope(failure: unknown): { code: string; message: string } {
  const value = failure as { error?: { code?: string; message?: string } } | undefined;
  return {
    code: value?.error?.code ?? "REQUEST_FAILED",
    message: value?.error?.message ?? "The request could not be completed.",
  };
}

/** Response labels mapped onto the one honesty pill. Never invented locally. */
export function honestyKinds(labels: readonly string[] | undefined): HonestyLabelKind[] {
  const kinds: HonestyLabelKind[] = [];
  for (const label of labels ?? []) {
    if (label === HONESTY_LABELS.sandbox) kinds.push("sandbox");
    else if (label === HONESTY_LABELS.simulated) kinds.push("simulated");
    else if (label === HONESTY_LABELS.mock) kinds.push("mock");
    else if (label === HONESTY_LABELS.demoSeed) kinds.push("demoSeed");
    else if (label.startsWith("FALLBACK:")) kinds.push("fallback");
  }
  return kinds;
}

/** A product key as words; a missing key is a lot without a published product. */
export function productName(productKey: string | null): string {
  if (!productKey) return "Lot";
  const words = productKey.replaceAll(/[-_]+/g, " ").trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : "Lot";
}

/** Short enough to scan in a heading; the full id stays in the code element. */
export function shortId(value: string): string {
  return value.length > 12 ? `${value.slice(0, 8)}…` : value;
}
