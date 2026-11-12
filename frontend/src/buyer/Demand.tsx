import { type FormEvent, useState } from "react";
import { Link } from "react-router-dom";
import { api, envelope, formatDateTime, Notice, useApiRead, type ApiComponents } from "../shared";

type Cluster = ApiComponents["schemas"]["DemandClusterView"];
type Signal = ApiComponents["schemas"]["DemandSignalRequest"];

export function DemandConsent({cluster, source, onClose}: {cluster?: Cluster; source: Signal["source"]; onClose: () => void}) {
  const [product, setProduct] = useState(cluster?.product_key ?? "");
  const [condition, setCondition] = useState<Signal["condition"]>((cluster?.condition as Signal["condition"]) ?? "NEW");
  const [variant, setVariant] = useState(cluster?.variant ?? "");
  const [bundle, setBundle] = useState(cluster?.bundle_contents.join("\n") ?? "");
  const [region, setRegion] = useState("");
  const [consented, setConsented] = useState(false);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [problem, setProblem] = useState("");
  async function save(event: FormEvent) {
    event.preventDefault();
    if (!consented || busy) return;
    setBusy(true); setProblem("");
    try {
      const {data, error} = await api.POST("/api/v1/me/demand-signals", {body: {
        product_key: product.trim(), condition, variant: variant.trim() || null,
        bundle_contents: bundle.split("\n").map((part) => part.trim()).filter(Boolean),
        region: region.trim().toUpperCase(), source,
      }});
      if (error || !data) setProblem(envelope(error).message);
      else setSaved(true);
    } catch { setProblem("Your interest could not be saved. Try again."); }
    finally { setBusy(false); }
  }
  if (saved) return <div className="shop-panel shop-panel-pad"><p role="status">Interest saved. We’ll notify you here when a pool is proposed and published. This is not a pool entry.</p><Link className="signup-back" to="/my-pools">Manage your interests</Link><button type="button" className="shop-quiet-button" onClick={onClose}>Done</button></div>;
  return <form aria-label="Demand notification consent" className="shop-panel shop-panel-pad grid gap-4" onSubmit={(event) => void save(event)}>
    <h3 className="font-semibold">Notify me when a pool forms</h3>
    <p className="shop-copy">Confirm the product and delivery region. We save these fields only after you consent, without your budget, message or address. This records interest; it does not join a pool or authorize payment. Notification is in-app only.</p>
    <label className="text-sm">Product key<input required maxLength={200} className="form-input mt-1" value={product} onChange={(event) => {setProduct(event.target.value); setConsented(false);}} placeholder="For example, ceramic-kettle" /></label>
    <div className="grid gap-4 sm:grid-cols-2"><label className="text-sm">Condition<select className="form-input mt-1" value={condition} onChange={(event) => {setCondition(event.target.value as Signal["condition"]); setConsented(false);}}><option value="NEW">New</option><option value="REFURBISHED">Refurbished</option><option value="OPEN_BOX">Open box</option></select></label>
      <label className="text-sm">Variant (optional)<input maxLength={200} className="form-input mt-1" value={variant} onChange={(event) => {setVariant(event.target.value); setConsented(false);}} /></label></div>
    <label className="text-sm">Bundle contents (one item per line)<textarea required rows={3} className="form-input mt-1" value={bundle} onChange={(event) => {setBundle(event.target.value); setConsented(false);}} /></label>
    <label className="text-sm">Delivery region (US state code)<input required pattern="[A-Za-z]{2}" maxLength={2} className="form-input mt-1" value={region} onChange={(event) => {setRegion(event.target.value); setConsented(false);}} placeholder="NY" /></label>
    <label className="flex items-start gap-3 text-sm"><input type="checkbox" className="mt-1" checked={consented} onChange={(event) => setConsented(event.target.checked)} />I confirm these product fields and consent to saving my interest and in-app notifications.</label>
    {problem ? <Notice kind="error" code="REQUEST_FAILED">{problem}</Notice> : null}
    <div className="flex flex-wrap gap-3"><button type="submit" className="button-primary" disabled={busy || !consented}>{busy ? "Saving…" : "Save interest"}</button><button type="button" className="button-secondary" disabled={busy} onClick={onClose}>Not now</button></div>
  </form>;
}

export function FormingDemand() {
  const records = useApiRead("/api/v1/demand-clusters", (signal) => api.GET("/api/v1/demand-clusters", {signal}));
  const [selected, setSelected] = useState<Cluster | null>(null);
  const rows = Array.isArray(records.data) ? records.data : [];
  return <section className="mt-8" aria-labelledby="forming-demand-title"><h2 id="forming-demand-title" className="text-lg font-semibold">Forming demand</h2>
    <p className="shop-copy">Shared interest can form a pool. At the published threshold, a draft goes to an operator for review. Publication is never automatic.</p>
    {records.error ? <Notice kind="error" code="REQUEST_FAILED">Forming demand could not be loaded. <button type="button" className="signup-back" onClick={() => void records.refetch()}>Retry forming demand</button></Notice>
      : records.isPending ? <p role="status" className="shop-copy">Loading forming demand…</p>
      : rows.length === 0 ? <p className="shop-copy">No forming demand yet.</p>
      : <ul className="grid gap-4 mt-4 sm:grid-cols-2">{rows.map((row) => <li key={row.cluster_key} className="shop-panel shop-panel-pad"><h3 className="font-semibold">{row.title}</h3><p className="shop-copy">{[row.variant, row.condition.toLowerCase().replaceAll("_", " ")].filter(Boolean).join(" · ")}</p><p className="shop-copy">Includes {row.bundle_contents.join(", ")}</p><p className="shop-copy">Regions: {row.regions.join(", ")}</p><p className="font-semibold mt-3">{row.interested} of {row.threshold} interested</p><p className="shop-copy">{row.status === "COLLECTING" ? "Collecting interest" : row.status === "PROPOSED" ? "Draft awaiting operator review" : "Pool published"}</p><button type="button" className="button-secondary mt-3" onClick={() => setSelected(row)}>Notify me</button></li>)}</ul>}
    {selected ? <div className="mt-4"><DemandConsent key={selected.cluster_key} cluster={selected} source="discover" onClose={() => setSelected(null)} /></div> : null}
  </section>;
}

export function Interests() {
  const records = useApiRead("/api/v1/me/demand-signals", (signal) => api.GET("/api/v1/me/demand-signals", {signal}));
  const [busy, setBusy] = useState<string | null>(null);
  const [problem, setProblem] = useState("");
  async function cancel(id: string) {
    setBusy(id); setProblem("");
    try {
      const {error} = await api.DELETE("/api/v1/me/demand-signals/{signal_id}", {params: {path: {signal_id: id}}});
      if (error) setProblem(envelope(error).message);
      else await records.refetch();
    } catch { setProblem("Your interest could not be cancelled. Try again."); }
    finally { setBusy(null); }
  }
  const rows = Array.isArray(records.data) ? records.data : [];
  return <section className="shop-panel shop-panel-pad mt-6" aria-labelledby="interests-title"><h2 id="interests-title" className="text-lg font-semibold">Interests</h2><p className="shop-copy">Products you asked to hear about. An interest is not an entry; join separately when a pool opens.</p>
    {problem ? <Notice kind="error" code="REQUEST_FAILED">{problem}</Notice> : null}
    {records.error ? <Notice kind="error" code="REQUEST_FAILED">Your interests could not be loaded. <button type="button" className="signup-back" onClick={() => void records.refetch()}>Retry interests</button></Notice> : records.isPending ? <p role="status">Loading interests…</p> : rows.length === 0 ? <p className="shop-copy">No active interests.</p> : <ul>{rows.map((row) => <li key={row.signal_id} className="delegation-record"><div><h3 className="font-semibold">{row.title}</h3><p>{row.interested} of {row.threshold} interested · {row.status.toLowerCase()}</p><p className="shop-copy">Expires {formatDateTime(row.expires_at)}</p>{row.pool_id && row.status === "POOLED" ? <Link className="signup-back" to={`/pools/${row.pool_id}`}>View pool</Link> : null}</div><button type="button" className="button-secondary" disabled={busy !== null} onClick={() => void cancel(row.signal_id)}>{busy === row.signal_id ? "Cancelling…" : "Cancel interest"}</button></li>)}</ul>}
  </section>;
}
