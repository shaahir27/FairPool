type BrandProps = {
  workspace?: string;
};

export function Brand({ workspace }: BrandProps) {
  return (
    <div className="flex items-center gap-3">
      <span
        aria-hidden="true"
        className="flex h-9 w-9 items-center justify-center rounded-lg bg-accent text-sm font-semibold text-surface"
      >
        FP
      </span>
      <div className="leading-tight">
        <p className="font-display text-lg text-ink">FairPool</p>
        <p className="text-[0.68rem] uppercase tracking-label text-muted">
          {workspace ?? "Group buying, sandbox demo"}
        </p>
      </div>
    </div>
  );
}
