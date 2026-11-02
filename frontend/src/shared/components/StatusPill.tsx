import type { ReactNode } from "react";

import type { StatusTone } from "../lib/status";

/**
 * One pill for honesty labels and statuses (the scaffold's only pill style).
 * The caller always also renders the API's raw value where it matters.
 */
const TONES: Readonly<Record<StatusTone, string>> = {
  neutral: "border-line bg-canvas text-muted",
  pending: "border-line bg-line/40 text-ink",
  active: "border-warn bg-accent-soft text-ink",
  good: "border-ink bg-ink text-canvas",
  bad: "border-danger bg-danger-soft text-danger",
};

export function StatusPill({
  status,
  tone = "neutral",
  children,
}: {
  status: string;
  tone?: StatusTone;
  children?: ReactNode;
}) {
  return (
    <span
      className={`inline-flex items-center rounded-full border px-3 py-1 text-[0.65rem] font-semibold uppercase tracking-label ${TONES[tone]}`}
      title={status}
    >
      {children ?? status}
    </span>
  );
}
