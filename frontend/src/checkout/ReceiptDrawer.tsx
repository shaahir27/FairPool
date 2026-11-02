import { useEffect, useRef, useState } from "react";
import { type ApiComponents, formatDateTime, Icon } from "../shared";

type Receipt = ApiComponents["schemas"]["EntryReceipt"];
export function ReceiptDrawer({ receipt, open, onClose }: { receipt: Receipt; open: boolean; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  const [message, setMessage] = useState("");
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);
  const fields: [string, string, string][] = [
    ["Commitment", receipt.payload.commitment, "A fingerprint of your entry"],
    ["Entry ID", receipt.payload.entry_id, "Your place in the pool"],
    ["Pool ID", receipt.payload.pool_id, "The pool you joined"],
    ["Received time", formatDateTime(receipt.payload.received_at), "When we got it"],
    ["Salt", receipt.salt_hex, "Keeps your fingerprint private"],
    ["Request hash", receipt.request_hash, "Fingerprint of your request"],
    ["Signature", receipt.signature, "Signed by FairPool"],
  ];
  const copy = async (label: string, value: string) => {
    try { await navigator.clipboard.writeText(value); setMessage(`${label} copied.`); }
    catch { setMessage(`Could not copy ${label.toLowerCase()}. Select the value to copy it manually.`); }
  };
  return <dialog ref={ref} className="receipt-drawer" aria-labelledby="receipt-title" aria-describedby="receipt-description" onCancel={onClose} onClose={onClose}
    onClick={(event) => {
      if (event.target !== event.currentTarget) return;
      const bounds = event.currentTarget.getBoundingClientRect();
      if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) onClose();
    }}>
    <div className="receipt-header"><h2 id="receipt-title"><Icon name="receipt" />Entry receipt</h2><button type="button" className="icon-button" aria-label="Close receipt" onClick={onClose} autoFocus><Icon name="close" /></button></div>
    <p id="receipt-description" className="secondary-copy mt-2">Proof that your entry was received. Opened from your order.</p>
    <dl className="receipt-fields">{fields.map(([label, value, help]) => <div className="receipt-field" key={label}><dt>{label}<button type="button" className="icon-button" aria-label={`Copy ${label.toLowerCase()}`} onClick={() => void copy(label, value)}><Icon name="copy" /></button></dt><dd>{value}<span className="receipt-help">{help}</span></dd></div>)}</dl>
    <p className="secondary-copy mt-3" role="status">{message}</p>
    <a className="mt-4 inline-block text-sm font-semibold underline underline-offset-4" href={`/audit/${receipt.payload.pool_id}`}>Check it on the public audit page</a>
  </dialog>;
}
