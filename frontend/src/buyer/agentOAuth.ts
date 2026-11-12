import { API_BASE_URL, getCsrfToken, type ApiComponents } from "../shared";

// OAuth routes deliberately stay out of OpenAPI (api.md §4.7).
export type AuthorizationRequest = {
  response_type: string; client_id: string; redirect_uri: string; state: string;
  code_challenge: string; code_challenge_method: string;
};
export type Authorization = AuthorizationRequest & { client_name: string };

export async function decideAuthorization(request: AuthorizationRequest, mandate?: ApiComponents["schemas"]["DelegationCreateRequest"]): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/oauth/authorize/decision`, {
    method: "POST", credentials: "include",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": getCsrfToken() ?? "" },
    body: JSON.stringify({ response_type: request.response_type, client_id: request.client_id, redirect_uri: request.redirect_uri, state: request.state, code_challenge: request.code_challenge, code_challenge_method: request.code_challenge_method, approved: Boolean(mandate), ...(mandate ? {
      scope: mandate.scope, max_cap_cents: mandate.max_cap_cents, expires_at: mandate.expires_at,
    } : {}) }),
  });
  const result = await response.json();
  if (!response.ok || typeof result.redirect_to !== "string") throw new Error("Consent could not be saved. Try again.");
  window.location.assign(result.redirect_to);
}
