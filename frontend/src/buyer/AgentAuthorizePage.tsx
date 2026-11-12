import { useState } from "react";
import { useLocation } from "react-router-dom";
import { API_BASE_URL, Notice, useApiRead } from "../shared";
import { AgentSettingsPage } from "./pages";
import { decideAuthorization, type AuthorizationRequest } from "./agentOAuth";

export function AgentAuthorizePage() {
  const { search } = useLocation();
  const params = new URLSearchParams(search);
  const request: AuthorizationRequest = {
    response_type: params.get("response_type") ?? "", client_id: params.get("client_id") ?? "",
    redirect_uri: params.get("redirect_uri") ?? "", state: params.get("state") ?? "",
    code_challenge: params.get("code_challenge") ?? "", code_challenge_method: params.get("code_challenge_method") ?? "",
  };
  const [denying, setDenying] = useState(false);
  const [problem, setProblem] = useState("");
  const preview = useApiRead(`oauth-consent:${search}`, async (signal) => {
    const response = await fetch(`${API_BASE_URL}/oauth/authorize?${new URLSearchParams(request)}`, {
      signal, credentials: "include", headers: { Accept: "application/json" },
    });
    if (!response.ok) throw new Error("Invalid authorization request");
    const data: {client_name: string; redirect_uri: string} = await response.json();
    return {data};
  });
  async function deny() {
    setDenying(true); setProblem("");
    try { await decideAuthorization(request); }
    catch { setProblem("Consent could not be saved. Try again."); setDenying(false); }
  }
  return <div className="buyer-settings agent-page agent-consent-page">
    <header className="settings-heading"><h1 className="shop-title">Connect an agent</h1><p className="shop-copy">Review the client and choose exactly what it may do.</p></header>
    {preview.isPending ? <p role="status">Checking the connection request…</p> : preview.error ?
      <Notice kind="error" code="INVALID_REQUEST">This connection request could not be verified. Return to your agent and connect again. <button type="button" className="signup-back" onClick={() => void preview.refetch()}>Try again</button></Notice> : preview.data ? <>
        <section className="settings-surface agent-consent-client"><div><h2>{preview.data.client_name}</h2><p className="shop-copy">Client names are supplied by their developers. Only approve a client you recognize.</p><p className="shop-copy mt-3">Requested redirect URI</p><code className="block break-all">{preview.data.redirect_uri}</code>
          <p className="shop-copy">This connection authorizes no payment. A human approves every charge.</p>
          </div><button type="button" className="button-secondary" disabled={denying} onClick={() => void deny()}>{denying ? "Returning to agent…" : "Deny"}</button>
          {problem ? <Notice kind="error" code="REQUEST_FAILED">{problem}</Notice> : null}
        </section>
        <AgentSettingsPage authorization={{...request, client_name: preview.data.client_name}} />
      </> : null}
  </div>;
}
