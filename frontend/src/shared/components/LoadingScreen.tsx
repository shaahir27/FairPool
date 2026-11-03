import { PoolMark } from "./Brand";

export function LoadingScreen({ label = "Opening FairPool", compact = false }: { label?: string; compact?: boolean }) {
  return <div className={`fairpool-loading ${compact ? "is-compact" : ""}`} role="status" aria-label={label} aria-busy="true">
    <div className="loading-emblem" aria-hidden="true"><span className="loading-orbit" /><PoolMark /></div>
    <div><p className="loading-brand">FairPool</p><p className="loading-message">{label}…</p></div>
    <div className="loading-track" aria-hidden="true"><span /></div>
  </div>;
}
