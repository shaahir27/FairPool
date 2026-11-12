import { useState } from "react";
import { api, envelope, formatDateTime, Notice, StatusPill, useApiRead } from "../shared";

export function DemandProposalsPanel() {
  const records = useApiRead("/api/v1/admin/demand-proposals", (signal) => api.GET("/api/v1/admin/demand-proposals", {signal}));
  const [busy, setBusy] = useState<string | null>(null);
  const [problem, setProblem] = useState("");
  const [message, setMessage] = useState("");
  async function decide(key: string, action: "publish" | "reject") {
    if (busy) return;
    setBusy(key); setProblem(""); setMessage("");
    try {
      const {error} = await api.POST(action === "publish" ? "/api/v1/admin/demand-proposals/{cluster_key}/publish" : "/api/v1/admin/demand-proposals/{cluster_key}/reject", {params: {path: {cluster_key: key}}});
      if (error) setProblem(envelope(error).message);
      else {setMessage(action === "publish" ? "Pool published. Interested buyers were notified in-app." : "Proposal rejected."); await records.refetch();}
    } catch { setProblem("The decision could not be saved. Try again."); }
    finally { setBusy(null); }
  }
  return <section aria-labelledby="demand-proposals-title" className="shop-panel shop-panel-pad ops-demand-panel"><h2 id="demand-proposals-title" className="text-lg font-semibold">Review queue</h2><p className="shop-copy">Review threshold-formed drafts. Publishing freezes the ordinary pool rules and schedules its opening; it never charges a buyer.</p>
    {message ? <p role="status" className="shop-copy">{message}</p> : null}
    {problem ? <Notice kind="error" code="REQUEST_FAILED">{problem}</Notice> : null}
    {records.error ? <Notice kind="error" code="REQUEST_FAILED">Demand proposals could not be loaded. <button type="button" className="signup-back" onClick={() => void records.refetch()}>Retry proposals</button></Notice> : records.isPending ? <p role="status">Loading demand proposals…</p> : !records.data?.length ? <p className="shop-copy">No demand proposals yet.</p> : <ul className="ops-demand-list">{records.data.map((row) => <li key={row.cluster_key} className="ops-demand-record"><div><h3 className="font-semibold">{row.title}</h3><p>{row.interested} distinct active interests · threshold {row.threshold}</p><p className="shop-copy">Regions: {row.regions.join(", ")}{row.proposed_at ? ` · Proposed ${formatDateTime(row.proposed_at)}` : ""}</p><details className="mt-2"><summary>Pool reference</summary><code className="break-all">{row.pool_id}</code></details></div><StatusPill status={row.status} />{row.status === "PROPOSED" ? <div className="flex flex-wrap gap-3"><button type="button" className="button-primary" disabled={busy !== null} onClick={() => void decide(row.cluster_key, "publish")}>Publish pool</button><button type="button" className="button-secondary" disabled={busy !== null} onClick={() => void decide(row.cluster_key, "reject")}>Reject proposal</button></div> : null}</li>)}</ul>}
  </section>;
}
