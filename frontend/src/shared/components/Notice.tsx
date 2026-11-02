import type { ReactNode } from "react";

/**
 * A page-level message. Business errors show the API's code and message, never
 * raw exception text (config-and-errors.md section 2).
 */
export function Notice({
  kind = "info",
  code,
  children,
}: {
  kind?: "info" | "warn" | "error";
  code?: string;
  children: ReactNode;
}) {
  const tones = {
    info: "border-line bg-accent-soft text-ink",
    warn: "border-warn/40 bg-warn-soft text-warn",
    error: "border-danger/40 bg-danger-soft text-danger",
  } as const;
  return (
    <div
      role={kind === "error" ? "alert" : "status"}
      aria-live="polite"
      className={`enter-rise flex items-start gap-3 rounded-xl border px-4 py-3 text-sm ${tones[kind]}`}
    >
      <span className="mt-0.5" aria-hidden="true">
        {kind === "error" ? "!" : kind === "warn" ? "!" : "i"}
      </span>
      <span>
        {code ? <code className="mr-2 font-mono text-xs font-semibold">{code}</code> : null}
        {children}
      </span>
    </div>
  );
}

export function FieldError({ code, children }: { code?: string; children: ReactNode }) {
  return (
    <p className="mt-1 text-xs text-danger" role="alert">
      {code ? <code className="mr-1 font-mono">{code}</code> : null}
      {children}
    </p>
  );
}
