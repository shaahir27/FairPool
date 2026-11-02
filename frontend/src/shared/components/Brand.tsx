type BrandProps = {
  workspace?: string;
};

export function PoolMark({ className = "" }: { className?: string }) {
  return (
    <svg className={`pool-mark ${className}`} viewBox="0 0 64 64" fill="none" aria-hidden="true">
      <rect width="64" height="64" rx="17" fill="currentColor" />
      <circle cx="32" cy="29" r="21" stroke="rgb(var(--color-canvas))" strokeOpacity=".25" strokeWidth="2" />
      <path d="M18 51V29a14 14 0 1 1 14 14H18" stroke="rgb(var(--color-canvas))" strokeWidth="5" strokeLinecap="round" />
      <circle cx="32" cy="29" r="5.5" fill="rgb(var(--color-mark))" />
    </svg>
  );
}

export function Brand({ workspace }: BrandProps) {
  return (
    <div className="brand" aria-label={workspace ? `FairPool · ${workspace}` : "FairPool"}>
      <PoolMark />
      <div className="brand-wordmark">Fair<span>Pool</span></div>
    </div>
  );
}
