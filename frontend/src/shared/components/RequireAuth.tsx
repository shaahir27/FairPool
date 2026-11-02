import { type ReactNode, useEffect, useState } from "react";
import { Navigate, useLocation } from "react-router-dom";

import { Notice } from "./Notice";
import { api } from "../api/client";
import { resetSessionCache, sessionState } from "../lib/session";

type GuardState = "checking" | "in" | "out" | "unreachable";

/**
 * Session gate for every buyer, merchant and ops route.
 *
 * The cookie is HttpOnly and lives 24 hours, so the browser cannot read it; the
 * server is the only thing that can say whether it is still valid. One `GET /me`
 * decides: 200 renders the route, 401 sends the visitor to `/login` with the path
 * they came from, and the login form returns them there.
 */
export function RequireAuth({ children }: { children: ReactNode }) {
  const location = useLocation();
  const [state, setState] = useState<GuardState>(() => sessionState() ?? "checking");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const known = sessionState();
    if (known !== null) {
      setState(known);
      return;
    }
    let live = true;
    api
      .GET("/api/v1/me")
      .then(({ response }) => {
        if (!live) return;
        // Only a 401 says the cookie is dead. A 500, a proxy error or a refused
        // request says nothing about the session and must not read as signed out.
        if (response.status === 401) {
          resetSessionCache("out");
          setState("out");
          return;
        }
        if (response.ok) {
          resetSessionCache("in");
          setState("in");
          return;
        }
        setState("unreachable");
      })
      .catch(() => {
        // A refused or unreachable request says nothing about the cookie, so it
        // must not read as signed out and must not hang on the blank spinner.
        if (live) setState("unreachable");
      });
    return () => {
      live = false;
    };
  }, [attempt]);

  if (state === "checking") {
    return (
      <div
        className="min-h-screen bg-canvas"
        aria-busy="true"
        aria-label="Checking your session"
      />
    );
  }
  if (state === "unreachable") {
    return (
      <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center gap-5 px-6">
        <h1 className="font-display text-2xl text-ink">Cannot reach FairPool</h1>
        <Notice kind="error" code="REQUEST_FAILED">
          The server did not answer, so your sign-in status is unknown. Nothing was
          signed out.
        </Notice>
        <button
          type="button"
          className="button-primary w-full"
          onClick={() => {
            resetSessionCache();
            setState("checking");
            setAttempt((count) => count + 1);
          }}
        >
          Try again
        </button>
      </main>
    );
  }
  if (state === "out") {
    return (
      <Navigate
        to="/login"
        replace
        state={{ from: location.pathname + location.search }}
      />
    );
  }
  return <>{children}</>;
}
