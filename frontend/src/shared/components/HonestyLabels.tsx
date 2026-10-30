import {
  HONESTY_LABELS,
  type HonestyLabelKind,
} from "../lib/labels";

type HonestyLabelsProps = {
  kinds?: readonly HonestyLabelKind[];
};

const DEFAULT_KINDS: readonly HonestyLabelKind[] = ["sandbox", "fallback"];

export function HonestyLabels({ kinds = DEFAULT_KINDS }: HonestyLabelsProps) {
  return (
    <ul
      aria-label="Honesty labels"
      className="flex flex-wrap items-center gap-2 text-[0.65rem] font-medium uppercase tracking-label"
    >
      {kinds.includes("sandbox") ? (
        <li className="rounded-full border border-line bg-canvas px-3 py-1 text-muted">
          {HONESTY_LABELS.sandbox}
        </li>
      ) : null}
      {kinds.includes("simulated") ? (
        <li className="rounded-full border border-warn bg-warn-soft px-3 py-1 text-warn">
          {HONESTY_LABELS.simulated}
        </li>
      ) : null}
      {kinds.includes("mock") ? (
        <li className="rounded-full border border-warn bg-warn-soft px-3 py-1 text-warn">
          {HONESTY_LABELS.mock}
        </li>
      ) : null}
      {kinds.includes("demoSeed") ? (
        <li className="rounded-full border border-line bg-canvas px-3 py-1 text-muted">
          {HONESTY_LABELS.demoSeed}
        </li>
      ) : null}
      {kinds.includes("fallback") ? (
        <li className="flex flex-wrap items-center gap-2 rounded-full border border-warn bg-warn-soft px-3 py-1 normal-case tracking-normal">
          <span className="font-semibold uppercase tracking-label text-warn">
            {HONESTY_LABELS.fallbackTag}
          </span>
          <span className="text-warn">{HONESTY_LABELS.fallbackSentence}</span>
        </li>
      ) : null}
    </ul>
  );
}
