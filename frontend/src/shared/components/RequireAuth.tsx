import { type ReactNode, useEffect, useState } from "react";
import { Navigate, useLocation } from "react-router-dom";

import { api } from "../api/client";
import { resetSessionCache, sessionState } from "../lib/session";

/**
 * Session gate for every buyer, merchant and ops route.
 *
 * The cookie is HttpOnly and lives 24 hours, so the browser cannot read it; the
 * server is the only thing that can say whether it is still valid. One `GET /me`
 * decides: 200 renders the route, anything else sends the visitor to `/login`
 * with the path it came from, and the login form returns them there.
 */
export function RequireAuth({ children }: { children: ReactNode }) {
  const location = useLocation();
  const [state, setState] = useState<"in" | "out" | "checking">(sessionState() ?? "checking");

  useEffect(() => {
    const known = sessionState();
    if (known !== null) {
      setState(known);
      return;
    }
    let live = true;
    void api.GET("/api/v1/me").then(({ response }) => {
      if (!live) return;
      const next = response.ok ? "in" : "out";
      resetSessionCache(next);
      setState(next);
    });
    return () => {
      live = false;
    };
  }, []);

  if (state === "checking") {
    return (
      <div className="min-h-screen bg-canvas" aria-busy="true" aria-label="Checking your session" />
    );
  }
  if (state === "out") {
    return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  }
  return <>{children}</>;
}
