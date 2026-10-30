type PlaceholderPageProps = {
  title: string;
  route: string;
  task: string;
  taskTitle: string;
  planned: readonly string[];
};

/**
 * One honest placeholder for every route. It names the task that will build
 * the real screen and never implies that a marketplace action works yet.
 */
export function PlaceholderPage({
  title,
  route,
  task,
  taskTitle,
  planned,
}: PlaceholderPageProps) {
  return (
    <article className="max-w-3xl">
      <p className="text-[0.68rem] font-semibold uppercase tracking-label text-accent">
        Placeholder
      </p>
      <h1 className="mt-3 font-display text-4xl leading-tight text-ink sm:text-5xl">
        {title}
      </h1>
      <p className="mt-4 max-w-2xl text-base leading-relaxed text-muted">
        This screen is a Phase 1 placeholder. It does not load data and no
        marketplace action works here yet.
      </p>

      <div className="mt-10 rounded-2xl border border-line bg-surface p-6 shadow-sm sm:p-8">
        <dl className="grid gap-6 sm:grid-cols-3">
          <div>
            <dt className="text-[0.65rem] uppercase tracking-label text-muted">
              Implementation task
            </dt>
            <dd className="mt-2 text-sm font-semibold text-ink">{task}</dd>
          </div>
          <div>
            <dt className="text-[0.65rem] uppercase tracking-label text-muted">
              Planned in
            </dt>
            <dd className="mt-2 text-sm text-ink">{taskTitle}</dd>
          </div>
          <div>
            <dt className="text-[0.65rem] uppercase tracking-label text-muted">
              Route
            </dt>
            <dd className="mt-2">
              <code className="rounded-md border border-line bg-canvas px-2 py-1 text-xs text-ink">
                {route}
              </code>
            </dd>
          </div>
        </dl>

        <div className="mt-8 border-t border-line pt-6">
          <h2 className="text-sm font-semibold text-ink">
            Planned content (from the specification)
          </h2>
          <ul className="mt-4 space-y-2 text-sm leading-relaxed text-muted">
            {planned.map((item) => (
              <li key={item} className="flex gap-3">
                <span aria-hidden="true" className="mt-2 h-1 w-1 shrink-0 rounded-full bg-accent" />
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>

      <p className="mt-6 text-xs leading-relaxed text-muted">
        Nothing on this page is a product claim. The shell exists so every route
        and its area boundary are in place before a feature task fills it in.
      </p>
    </article>
  );
}
