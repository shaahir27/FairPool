import { useEffect, useId, useRef } from "react";

export function ConfirmAction({ title, message, confirmLabel, cancelLabel, busy, returnFocusId, onConfirm, onCancel }: {
  title: string; message: string; confirmLabel: string; cancelLabel: string; busy: boolean;
  returnFocusId: string;
  onConfirm: () => void; onCancel: () => void;
}) {
  const heading = useId();
  const description = useId();
  const cancel = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    cancel.current?.focus();
    return () => { queueMicrotask(() => document.getElementById(returnFocusId)?.focus()); };
  }, [returnFocusId]);
  return <div className="settings-confirm" role="alertdialog" aria-labelledby={heading} aria-describedby={description}
    onKeyDown={(event) => { if (event.key === "Escape" && !busy) onCancel(); }}>
    <h3 id={heading}>{title}</h3><p id={description}>{message}</p>
    <div className="settings-actions"><button type="button" className="button-secondary" disabled={busy} onClick={onConfirm}>{busy ? "Revoking…" : confirmLabel}</button>
      <button ref={cancel} type="button" className="shop-quiet-button" disabled={busy} onClick={onCancel}>{cancelLabel}</button></div>
  </div>;
}
