/**
 * The information panel the auth screens carry: what FairPool does, in three
 * real steps, plus the demo limits. No counts, no claims the API does not serve.
 */
const STEPS = [
  {
    title: "Describe what you want",
    body: "Say the product and your maximum price. Joining costs nothing.",
  },
  {
    title: "A published rule fills the lots",
    body: "When the pool closes, entries become commitments, a public seed is drawn, and the published rule orders them.",
  },
  {
    title: "You approve the payment",
    body: "PayPal places a hold only after a merchant and an exact price are known and you approve.",
  },
] as const;

const LIMITS = [
  "PayPal Sandbox only — no real money moves",
  "One stand-in test seller; no real merchant is paid",
  "US payers, USD only",
  "Generic demo products",
] as const;

export function AuthAside({ headline, valueLine }: { headline: string; valueLine: string }) {
  return (
    <section className="flex flex-col gap-8" aria-label="How FairPool works">
      <div className="enter-rise">
        <h2 className="max-w-[22ch] font-display text-4xl leading-[1.05] tracking-tight">
          {headline}
        </h2>
        <p className="mt-4 max-w-[46ch] text-base text-muted">{valueLine}</p>
      </div>
      <ol className="flex flex-col gap-5">
        {STEPS.map((step, index) => (
          <li
            key={step.title}
            className="enter-rise flex gap-3 border-l-2 border-ink/20 pl-4"
            style={{ animationDelay: `${index * 60}ms` }}
          >
            <span>
              <span className="block text-sm font-semibold">{step.title}</span>
              <span className="mt-1 block max-w-[46ch] text-sm text-muted">{step.body}</span>
            </span>
          </li>
        ))}
      </ol>
      <div className="rounded-xl border border-line bg-surface p-4">
        <p className="text-xs font-semibold uppercase tracking-label text-muted">
          This is a PayPal Sandbox demo
        </p>
        <ul className="mt-2 grid gap-1 text-sm text-muted">
          {LIMITS.map((limit) => (
            <li key={limit}>{limit}</li>
          ))}
        </ul>
      </div>
    </section>
  );
}
